import importlib
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conftest  # noqa: E402,F401  (installs Home Assistant stubs on import)

logic_mod = importlib.import_module("custom_components.vigobus.logic")
gtfs_mod = importlib.import_module("custom_components.vigobus.gtfs")
coordinator_mod = importlib.import_module("custom_components.vigobus.coordinator")
calendar_mod = importlib.import_module("custom_components.vigobus.calendar")
binary_mod = importlib.import_module("custom_components.vigobus.binary_sensor")
event_mod = importlib.import_module("custom_components.vigobus.event")

from test_coordinator_alert_notifications import _alert, _FakeEntry, _FakeHass  # noqa: E402

TODAY = date(2026, 11, 11)


def _active(pub_id, title, kind="info", inicio="2026-11-01", fin="2026-11-30", lineas="C1, A", stops=("Casa",)):
    return {
        **_alert(pub_id, title, lineas=lineas, inicio=inicio, fin=fin),
        "status": "active",
        "kind": kind,
        "description": f"Descripción de {title}",
        "stops": list(stops),
    }


class _Coord:
    def __init__(self, alerts):
        self.data = {"a": {"stop_name": "Casa", "alerts": alerts}}


class AlertEventSpanTests(unittest.TestCase):
    def test_range_becomes_an_all_day_event_with_an_exclusive_end(self):
        span = logic_mod.alert_event_span({"inicio": "2026-11-10", "fin": "2026-11-12"}, TODAY)
        self.assertEqual(span, (date(2026, 11, 10), date(2026, 11, 13)))

    def test_expired_alerts_have_no_event(self):
        self.assertIsNone(logic_mod.alert_event_span({"inicio": "2026-11-01", "fin": "2026-11-10"}, TODAY))

    def test_missing_dates_degrade_to_today(self):
        self.assertEqual(logic_mod.alert_event_span({}, TODAY), (TODAY, TODAY + timedelta(days=1)))
        self.assertEqual(
            logic_mod.alert_event_span({"inicio": "2026-11-12"}, TODAY), (date(2026, 11, 12), date(2026, 11, 13))
        )

    def test_end_before_start_is_clamped(self):
        span = logic_mod.alert_event_span({"inicio": "2026-11-20", "fin": "2026-11-15"}, TODAY)
        self.assertEqual(span, (date(2026, 11, 20), date(2026, 11, 21)))


class SplitLinesTextTests(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(logic_mod.split_lines_text("25, 11"), ["25", "11"])
        self.assertEqual(logic_mod.split_lines_text(["A", " C1 "]), ["A", "C1"])
        self.assertEqual(logic_mod.split_lines_text(None), [])


class NextDeparturesTests(unittest.TestCase):
    def _index(self):
        # One pattern 25: stops S1 -> S2 -> S3, three trips (06:00, 08:30, 23:50 at S1),
        # the middle one only runs on a service that is not active today.
        def hm(h, m):
            return h * 3600 + m * 60

        return {
            "routes_by_stop": {"S1": [(0, 0)], "S2": [(0, 1)], "S3": [(0, 2)]},
            "patterns": [
                {
                    "line": "25",
                    "headsign": "CENTRO",
                    "stops": ("S1", "S2", "S3"),
                    "service_ids": ["WK", "SUN", "WK"],
                    "dep": [
                        [hm(6, 0), hm(8, 30), hm(23, 50)],
                        [hm(6, 5), hm(8, 35), hm(23, 55)],
                        [hm(6, 10), hm(8, 40), hm(24, 0)],
                    ],
                }
            ],
            "calendar_rules": [],
            "added_dates": {"20261111": frozenset({"WK"}), "20261112": frozenset({"WK"})},
            "removed_dates": {},
            "_active_cache": {},
        }

    def test_next_departure_skips_services_that_do_not_run(self):
        out = gtfs_mod.next_departures(self._index(), "S1", "20261111", 7 * 3600, limit=2)
        self.assertEqual([r["seconds"] for r in out], [23 * 3600 + 50 * 60])  # the 08:30 trip is a Sunday service
        self.assertFalse(out[0]["next_day"])
        self.assertEqual(out[0]["line"], "25")
        self.assertEqual(out[0]["headsign"], "CENTRO")

    def test_rolls_over_to_tomorrow_when_nothing_is_left_today(self):
        out = gtfs_mod.next_departures(self._index(), "S1", "20261111", 23 * 3600 + 59 * 60)
        self.assertTrue(out[0]["next_day"])
        self.assertEqual(out[0]["seconds"], 6 * 3600)

    def test_the_last_stop_of_a_trip_has_no_departure(self):
        self.assertEqual(gtfs_mod.next_departures(self._index(), "S3", "20261111", 0), [])

    def test_unknown_stop(self):
        self.assertEqual(gtfs_mod.next_departures(self._index(), "nope", "20261111", 0), [])

    def test_cached_index_never_downloads(self):
        gtfs_mod._GTFS_CACHE["data"] = None
        self.assertIsNone(gtfs_mod.cached_index())


class CalendarTests(unittest.IsolatedAsyncioTestCase):
    def _entity(self, alerts):
        return calendar_mod.VigoBusAlertsCalendar(_Coord(alerts), "e1")

    def test_each_distinct_alert_is_an_all_day_event(self):
        entity = self._entity([_active("p1", "Huelga", kind="strike", inicio="2026-11-10", fin="2026-11-11")])
        events = entity._events(TODAY)

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual((event.start, event.end), (date(2026, 11, 10), date(2026, 11, 12)))
        self.assertEqual(event.summary, "Huelga")
        self.assertEqual(event.uid, "p1")
        self.assertIn("Líneas: C1, A", event.description)
        self.assertIn("Paradas: Casa", event.description)

    def test_expired_alerts_are_left_out(self):
        entity = self._entity([_active("old", "Caducado", inicio="2026-01-01", fin="2026-01-02")])
        self.assertEqual(entity._events(TODAY), [])

    def test_event_property_prefers_the_alert_in_force_that_ends_first(self):
        today = datetime.now().date()
        entity = self._entity(
            [
                _active("late", "Larga", inicio=str(today - timedelta(days=5)), fin=str(today + timedelta(days=30))),
                _active("soon", "Corta", inicio=str(today - timedelta(days=1)), fin=str(today + timedelta(days=1))),
                _active("next", "Futura", inicio=str(today + timedelta(days=3)), fin=str(today + timedelta(days=4))),
            ]
        )
        self.assertEqual(entity.event.uid, "soon")

    def test_event_property_falls_back_to_the_next_upcoming_alert(self):
        today = datetime.now().date()
        entity = self._entity(
            [
                _active("b", "B", inicio=str(today + timedelta(days=9)), fin=str(today + timedelta(days=10))),
                _active("a", "A", inicio=str(today + timedelta(days=3)), fin=str(today + timedelta(days=4))),
            ]
        )
        self.assertEqual(entity.event.uid, "a")
        self.assertIsNone(self._entity([]).event)

    async def test_get_events_returns_only_those_overlapping_the_window(self):
        today = datetime.now().date()
        entity = self._entity(
            [
                _active("in", "Dentro", inicio=str(today), fin=str(today + timedelta(days=2))),
                _active("out", "Fuera", inicio=str(today + timedelta(days=40)), fin=str(today + timedelta(days=41))),
            ]
        )
        start = datetime.combine(today, datetime.min.time())
        events = await entity.async_get_events(None, start, start + timedelta(days=7))
        self.assertEqual([e.uid for e in events], ["in"])


class KindBinarySensorTests(unittest.TestCase):
    def _sensor(self, alerts, kind="strike"):
        return binary_mod.VigoBusAlertKindBinarySensor(_Coord(alerts), "e1", kind, binary_mod.ALERT_KIND_BINARY_SENSORS[kind])

    def test_on_only_for_active_alerts_of_that_kind(self):
        sensor = self._sensor([_active("p1", "Huelga", kind="strike"), _active("p2", "Corte", kind="closure")])
        self.assertTrue(sensor.is_on)
        self.assertEqual(sensor.extra_state_attributes["count"], 1)
        self.assertEqual(sensor.extra_state_attributes["titles"], ["Huelga"])
        self.assertEqual(sensor.extra_state_attributes["lines"], ["A", "C1"])
        self.assertEqual(sensor.extra_state_attributes["stops"], ["Casa"])

    def test_upcoming_alerts_do_not_turn_it_on(self):
        upcoming = {**_active("p1", "Huelga futura", kind="strike"), "status": "upcoming"}
        self.assertFalse(self._sensor([upcoming]).is_on)

    def test_off_without_alerts(self):
        self.assertFalse(self._sensor([]).is_on)
        self.assertFalse(self._sensor([_active("p2", "Corte", kind="closure")]).is_on)

    def test_names_and_unique_ids(self):
        sensor = self._sensor([], kind="stop_closed")
        self.assertEqual(sensor._attr_name, "VigoBus paradas anuladas en vigor")
        self.assertEqual(sensor._attr_unique_id, "vigobus_e1_aviso_stop_closed")


class LifecycleEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._sent = []
        self._orig_dispatch = coordinator_mod.async_dispatcher_send
        coordinator_mod.async_dispatcher_send = lambda hass, signal, payload: self._sent.append((signal, payload))
        self._orig_notif = coordinator_mod.persistent_notification.async_create
        coordinator_mod.persistent_notification.async_create = lambda *a, **k: None

    def tearDown(self):
        coordinator_mod.async_dispatcher_send = self._orig_dispatch
        coordinator_mod.persistent_notification.async_create = self._orig_notif

    def _coord(self):
        return coordinator_mod.VigoBusCoordinator(_FakeHass(), _FakeEntry(data={}))

    def _lifecycle(self):
        return [p for s, p in self._sent if s.startswith("vigobus_alert_lifecycle_")]

    async def test_alert_started_when_an_upcoming_alert_comes_into_force(self):
        coord = self._coord()
        upcoming = {**_alert("p1", "Corte"), "status": "upcoming"}
        await coord._maybe_notify_new_alerts({"a": {"alerts": [upcoming]}})  # baseline

        await coord._maybe_notify_new_alerts({"a": {"alerts": [{**upcoming, "status": "active"}]}})

        self.assertEqual([item[0] for batch in self._lifecycle() for item in batch], ["alert_started"])

    async def test_no_started_event_for_an_alert_that_was_already_active(self):
        coord = self._coord()
        active = {**_alert("p1", "Corte"), "status": "active"}
        await coord._maybe_notify_new_alerts({"a": {"alerts": [active]}})
        await coord._maybe_notify_new_alerts({"a": {"alerts": [active]}})
        self.assertEqual(self._lifecycle(), [])

    async def test_alert_ended_only_after_it_has_been_gone_for_a_few_scans(self):
        coord = self._coord()
        active = {**_alert("p1", "Corte"), "status": "active"}
        await coord._maybe_notify_new_alerts({"a": {"alerts": [active]}})

        for _ in range(coordinator_mod.ALERT_FORGET_CYCLES - 1):
            await coord._maybe_notify_new_alerts({"a": {"alerts": []}})
        self.assertEqual(self._lifecycle(), [])

        await coord._maybe_notify_new_alerts({"a": {"alerts": []}})
        ended = [item for batch in self._lifecycle() for item in batch]
        self.assertEqual([item[0] for item in ended], ["alert_ended"])
        self.assertEqual(ended[0][1]["title"], "Corte")  # the last known version of the alert

    async def test_a_stale_feed_never_ends_an_alert(self):
        coord = self._coord()
        await coord._maybe_notify_new_alerts({"a": {"alerts": [{**_alert("p1", "Corte"), "status": "active"}]}})
        for _ in range(6):
            await coord._maybe_notify_new_alerts({"a": {"alerts": []}}, fresh=False)
        self.assertEqual(self._lifecycle(), [])


class _Bus:
    def __init__(self):
        self.fired = []

    def async_fire(self, name, data):
        self.fired.append((name, data))


class EventEntityTests(unittest.TestCase):
    def _entity(self):
        entity = event_mod.VigoBusAlertEvent("e1")
        entity.hass = type("H", (), {"bus": _Bus()})()
        return entity

    def test_event_types(self):
        self.assertEqual(event_mod.VigoBusAlertEvent._attr_event_types, ["new_alert", "alert_started", "alert_ended"])

    def test_lifecycle_fires_the_entity_event_and_a_bus_event_per_alert(self):
        entity = self._entity()
        alert = {**_alert("p9", "Corte"), "kind": "closure", "status": "active", "description": "d"}

        entity._handle_lifecycle([("alert_started", alert), ("alert_ended", alert)])

        self.assertEqual([e[0] for e in entity._fired], ["alert_started", "alert_ended"])
        self.assertEqual(entity._fired[0][1]["id"], "p9")
        self.assertEqual(entity._fired[0][1]["kind"], "closure")
        self.assertEqual([n for n, _ in entity.hass.bus.fired], ["vigobus_alert_started", "vigobus_alert_ended"])
        self.assertEqual(entity.hass.bus.fired[0][1]["entry_id"], "e1")


class AlertsFeedRepairTests(unittest.TestCase):
    def setUp(self):
        self.created, self.deleted = [], []
        self._orig = (coordinator_mod.ir.async_create_issue, coordinator_mod.ir.async_delete_issue)
        coordinator_mod.ir.async_create_issue = lambda hass, domain, issue_id, **kw: self.created.append((issue_id, kw))
        coordinator_mod.ir.async_delete_issue = lambda hass, domain, issue_id: self.deleted.append(issue_id)

    def tearDown(self):
        coordinator_mod.ir.async_create_issue, coordinator_mod.ir.async_delete_issue = self._orig

    def _coord(self):
        return coordinator_mod.VigoBusCoordinator(_FakeHass(), _FakeEntry(data={}))

    def test_issue_raised_after_the_threshold_and_only_once(self):
        coord = self._coord()
        for _ in range(coordinator_mod.ALERTS_FEED_ISSUE_THRESHOLD - 1):
            coord._track_alerts_feed(False)
        self.assertEqual(self.created, [])

        coord._track_alerts_feed(False)
        coord._track_alerts_feed(False)

        self.assertEqual(len(self.created), 1)
        issue_id, kwargs = self.created[0]
        self.assertEqual(issue_id, "alerts_feed_unavailable_test_entry")
        self.assertFalse(kwargs["is_fixable"])
        self.assertEqual(kwargs["translation_key"], "alerts_feed_unavailable")

    def test_issue_is_cleared_when_the_feed_recovers(self):
        coord = self._coord()
        for _ in range(coordinator_mod.ALERTS_FEED_ISSUE_THRESHOLD):
            coord._track_alerts_feed(False)
        coord._track_alerts_feed(True)

        self.assertEqual(self.deleted, ["alerts_feed_unavailable_test_entry"])
        coord._track_alerts_feed(True)
        self.assertEqual(len(self.deleted), 1)  # nothing more to clear

    def test_a_success_in_between_resets_the_count(self):
        coord = self._coord()
        for _ in range(coordinator_mod.ALERTS_FEED_ISSUE_THRESHOLD - 1):
            coord._track_alerts_feed(False)
        coord._track_alerts_feed(True)
        for _ in range(coordinator_mod.ALERTS_FEED_ISSUE_THRESHOLD - 1):
            coord._track_alerts_feed(False)
        self.assertEqual(self.created, [])


if __name__ == "__main__":
    unittest.main()
