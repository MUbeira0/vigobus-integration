import importlib
import unittest
from datetime import date

import conftest  # noqa: F401  (installs Home Assistant stubs on import)

api_mod = importlib.import_module("custom_components.vigobus.api")
logic_mod = importlib.import_module("custom_components.vigobus.logic")
coordinator_mod = importlib.import_module("custom_components.vigobus.coordinator")
sensor_mod = importlib.import_module("custom_components.vigobus.sensor")

from test_coordinator_alert_notifications import _alert, _FakeEntry, _FakeHass  # noqa: E402


class ClassifyAlertTests(unittest.TestCase):
    def test_kinds_for_real_titles(self):
        cases = {
            "SERVICIOS MÍNIMOS HUELGA GENERAL 11 DE NOVIEMBRE DE 2026": "strike",
            "CORTE TRÁFICO POLICARPO SANZ (MONTAJE ATRACCIONES NAVIDEÑAS)": "closure",
            "ACTUALIZACIÓN CORTE TRÁFICO CESÁREO VÁZQUEZ": "closure",
            "PARADA DE LA AVD. GARCÍA BARBÓN, 43 - ANULADA": "stop_closed",
            "Ruta anulada por obras": "works",
            "Parada anulada en Urzaiz": "stop_closed",
            "Desvío de la línea 15": "detour",
            "Cambio de horario nocturno": "schedule",
            "Algo sin palabras clave": "info",
        }
        for title, kind in cases.items():
            self.assertEqual(api_mod.classify_alert(title), kind, title)

    def test_falls_back_to_the_summary(self):
        self.assertEqual(api_mod.classify_alert("Aviso 12", "Habrá una huelga el lunes"), "strike")

    def test_empty_values(self):
        self.assertEqual(api_mod.classify_alert(None, None), "info")


class AlertDatesTests(unittest.TestCase):
    today = date(2026, 11, 11)

    def test_parses_both_date_formats(self):
        self.assertEqual(logic_mod.parse_alert_date("2026-11-10"), date(2026, 11, 10))
        self.assertEqual(logic_mod.parse_alert_date("10-11-2026"), date(2026, 11, 10))
        self.assertIsNone(logic_mod.parse_alert_date("ayer"))
        self.assertIsNone(logic_mod.parse_alert_date(None))
        self.assertIsNone(logic_mod.parse_alert_date("2026-13-45"))

    def test_status(self):
        status = lambda inicio, fin: logic_mod.alert_status({"inicio": inicio, "fin": fin}, self.today)  # noqa: E731
        self.assertEqual(status("2026-11-10", "2026-11-11"), "active")  # ends today: still in force
        self.assertEqual(status("2026-11-01", "2026-11-10"), "expired")
        self.assertEqual(status("2026-11-12", "2026-12-01"), "upcoming")
        self.assertEqual(status(None, None), "active")  # unreadable dates are never hidden
        self.assertEqual(status("2026-11-01", None), "active")


class CollectAlertsTests(unittest.TestCase):
    def test_counts_each_alert_once_across_stops(self):
        shared = {**_alert("p1", "Huelga"), "status": "active"}
        results = {
            "a": {"stop_name": "Stop A", "alerts": [shared]},
            "b": {"stop_name": "Stop B", "alerts": [shared, {**_alert("p2", "Corte"), "status": "upcoming"}]},
            "c": {"stop_name": "Stop C", "alerts": [shared]},
        }

        alerts = logic_mod.collect_alerts(results)

        self.assertEqual([a["id_publicacion"] for a in alerts], ["p1", "p2"])  # active first
        self.assertEqual(alerts[0]["stops"], ["Stop A", "Stop B", "Stop C"])
        self.assertEqual(alerts[1]["stops"], ["Stop B"])

    def test_same_id_with_edited_title_is_the_same_alert(self):
        results = {
            "a": {"alerts": [{**_alert("p1", "Corte"), "status": "active"}]},
            "b": {"alerts": [{**_alert("p1", "ACTUALIZACIÓN Corte"), "status": "active"}]},
        }
        self.assertEqual(len(logic_mod.collect_alerts(results)), 1)

    def test_ignores_malformed_data(self):
        self.assertEqual(logic_mod.collect_alerts(None), [])
        self.assertEqual(logic_mod.collect_alerts({"a": "nope", "b": {"alerts": [None, "x"]}}), [])


class StatusSensorTests(unittest.TestCase):
    def test_active_alerts_are_distinct_not_summed_per_stop(self):
        shared = {**_alert("p1", "Huelga"), "status": "active"}
        results = {
            "a": {"stop_name": "A", "alerts": [shared], "alerts_count": 1},
            "b": {"stop_name": "B", "alerts": [shared, {**_alert("p2", "Futuro"), "status": "upcoming"}], "alerts_count": 1},
            "c": {"stop_name": "C", "alerts": [shared], "alerts_count": 1},
        }

        class _Coordinator:
            data = results
            _consecutive_failures = 0
            _last_success_at = "x"
            _last_error_at = None

        sensor = sensor_mod.VigoBusStatusSensor.__new__(sensor_mod.VigoBusStatusSensor)
        sensor.coordinator = _Coordinator()

        attrs = sensor.extra_state_attributes

        self.assertEqual(attrs["active_alerts"], 1)  # was 3 (one per stop)
        self.assertEqual(attrs["upcoming_alerts"], 1)
        self.assertEqual(len(attrs["alerts"]), 2)


class DerivedSensorAttributesTests(unittest.TestCase):
    def test_line_route_upcoming_do_not_repeat_the_heavy_payload(self):
        class _Coordinator:
            data = {
                "Urzaiz": {
                    "stop_name": "Urzaiz",
                    "alerts": [{**_alert("p1", "Huelga"), "status": "active"}],
                    "alerts_count": 1,
                    "data": {"estimaciones": [{"linea": "C1", "ruta": "X", "minutos": 3, "metros": 10}]},
                }
            }

        for cls in (sensor_mod.VigoBusLineSensor, sensor_mod.VigoBusRouteSensor, sensor_mod.VigoBusUpcomingSensor):
            sensor = cls(_Coordinator(), "Urzaiz", entry_id="e", display_name="Urzaiz")
            attrs = sensor.extra_state_attributes
            self.assertNotIn("alerts", attrs, cls.__name__)
            self.assertNotIn("buses", attrs, cls.__name__)
            self.assertEqual(attrs["alerts_count"], 1)
            self.assertEqual(attrs["stop_name"], "Urzaiz")

        main = sensor_mod.VigoBusSensor(_Coordinator(), "Urzaiz", entry_id="e", display_name="Urzaiz")
        self.assertIn("alerts", main.extra_state_attributes)
        self.assertIn("buses", main.extra_state_attributes)


class AttachAlertsTests(unittest.TestCase):
    def _coord(self):
        return coordinator_mod.VigoBusCoordinator(_FakeHass(), _FakeEntry(data={}))

    def test_drops_expired_marks_upcoming_and_counts_only_active(self):
        index = {
            "C1": [
                {**_alert("old", "Caducado", fin="2000-01-01", inicio="1999-01-01")},
                {**_alert("now", "En vigor", inicio="2000-01-01", fin="2999-01-01")},
                {**_alert("soon", "Futuro", inicio="2998-01-01", fin="2999-01-01")},
            ]
        }
        result = {"data": {"estimaciones": [{"linea": "C1"}]}}

        out = self._coord()._attach_alerts(result, index)

        self.assertEqual([a["id_publicacion"] for a in out["alerts"]], ["now", "soon"])
        self.assertEqual([a["status"] for a in out["alerts"]], ["active", "upcoming"])
        self.assertEqual(out["alerts_count"], 1)

    def test_upcoming_only_does_not_flip_the_service_status(self):
        coord = self._coord()
        coord.data = {"a": {"alerts": [], "alerts_count": 0}}
        self.assertEqual(coord.service_status, "ok")


class NotificationResilienceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._sent = []
        self._original_create = coordinator_mod.persistent_notification.async_create
        coordinator_mod.persistent_notification.async_create = (
            lambda hass, message, title=None, notification_id=None: self._sent.append(message)
        )

    def tearDown(self):
        coordinator_mod.persistent_notification.async_create = self._original_create

    def _coord(self):
        return coordinator_mod.VigoBusCoordinator(_FakeHass(), _FakeEntry(data={"notify_new_alerts_enabled": True}))

    async def test_feed_outage_does_not_reannounce_everything_on_recovery(self):
        coord = self._coord()
        stops = {"nearest": {"alerts": [_alert("p1", "Corte C1")]}}
        await coord._maybe_notify_new_alerts(stops)  # baseline

        # The alerts feed is down for a few cycles: the snapshot is not fresh.
        for _ in range(5):
            await coord._maybe_notify_new_alerts({"nearest": {"alerts": []}}, fresh=False)

        await coord._maybe_notify_new_alerts(stops)  # feed is back, same alert
        self.assertEqual(self._sent, [])

    async def test_edited_alert_with_the_same_id_is_not_new(self):
        coord = self._coord()
        await coord._maybe_notify_new_alerts({"nearest": {"alerts": [_alert("p1", "Corte C1", fin="2026-01-02")]}})

        await coord._maybe_notify_new_alerts(
            {"nearest": {"alerts": [_alert("p1", "ACTUALIZACIÓN Corte C1", fin="2026-02-02")]}}
        )

        self.assertEqual(self._sent, [])

    async def test_one_stop_missing_for_a_cycle_does_not_reannounce(self):
        coord = self._coord()
        both = {"a": {"alerts": [_alert("p1", "Corte")]}, "b": {"alerts": [_alert("p2", "Otro")]}}
        await coord._maybe_notify_new_alerts(both)

        await coord._maybe_notify_new_alerts({"b": {"alerts": [_alert("p2", "Otro")]}})  # stop "a" failed to load
        await coord._maybe_notify_new_alerts(both)

        self.assertEqual(self._sent, [])

    async def test_an_alert_gone_for_good_is_forgotten_and_announced_if_it_returns(self):
        coord = self._coord()
        await coord._maybe_notify_new_alerts({"a": {"alerts": [_alert("p1", "Corte")]}})

        for _ in range(coordinator_mod.ALERT_FORGET_CYCLES):
            await coord._maybe_notify_new_alerts({"a": {"alerts": []}})
        self.assertEqual(self._sent, [])

        await coord._maybe_notify_new_alerts({"a": {"alerts": [_alert("p1", "Corte")]}})
        self.assertEqual(len(self._sent), 1)


if __name__ == "__main__":
    unittest.main()
