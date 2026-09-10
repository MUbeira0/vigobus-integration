import importlib
import unittest

import conftest  # noqa: F401  (installs Home Assistant stubs on import)

coordinator_mod = importlib.import_module("custom_components.vigobus.coordinator")


class _FakeStates:
    def get(self, entity_id):
        return None

    def async_all(self, domain):
        return []


class _FakeConfig:
    latitude = 42.2406
    longitude = -8.7207


class _FakeHass:
    def __init__(self):
        self.states = _FakeStates()
        self.config = _FakeConfig()


class _FakeEntry:
    def __init__(self, data=None, options=None):
        self.data = data or {}
        self.options = options or {}
        self.entry_id = "test_entry"


def _alert(pub_id, title, lineas="C1", inicio="2026-01-01", fin="2026-01-02"):
    return {
        "id_publicacion": pub_id,
        "title": title,
        "lineas": lineas,
        "inicio": inicio,
        "fin": fin,
    }


class NewAlertNotificationTests(unittest.TestCase):
    def setUp(self):
        self._sent = []
        self._original_create = coordinator_mod.persistent_notification.async_create
        coordinator_mod.persistent_notification.async_create = (
            lambda hass, message, title=None, notification_id=None: self._sent.append(
                {"message": message, "title": title, "notification_id": notification_id}
            )
        )

    def tearDown(self):
        coordinator_mod.persistent_notification.async_create = self._original_create

    def _make(self, notify_new_alerts_enabled=True):
        hass = _FakeHass()
        entry = _FakeEntry(data={"notify_new_alerts_enabled": notify_new_alerts_enabled})
        return coordinator_mod.VigoBusCoordinator(hass, entry)

    def test_first_cycle_establishes_baseline_without_notifying(self):
        # A restart (or a fresh coordinator) should never announce every
        # already-active alert as "new" — only alerts that show up *after*
        # that first baseline cycle count as new.
        coord = self._make()
        results = {"nearest": {"alerts": [_alert("p1", "Corte C1")]}}

        coord._maybe_notify_new_alerts(results)

        self.assertEqual(self._sent, [])
        self.assertTrue(coord._alerts_baseline_done)
        self.assertIn(("p1", "Corte C1", "2026-01-01", "2026-01-02"), coord._notified_alert_ids)

    def test_notifies_once_for_an_alert_appearing_after_baseline(self):
        coord = self._make()
        coord._maybe_notify_new_alerts({"nearest": {"alerts": [_alert("p1", "Corte C1")]}})

        coord._maybe_notify_new_alerts(
            {"nearest": {"alerts": [_alert("p1", "Corte C1"), _alert("p2", "Corte C2", lineas="C2")]}}
        )

        self.assertEqual(len(self._sent), 1)
        self.assertIn("Corte C2", self._sent[0]["message"])
        self.assertNotIn("Corte C1", self._sent[0]["message"])

        # Same state again next cycle: no duplicate notification.
        coord._maybe_notify_new_alerts(
            {"nearest": {"alerts": [_alert("p1", "Corte C1"), _alert("p2", "Corte C2", lineas="C2")]}}
        )
        self.assertEqual(len(self._sent), 1)

    def test_bundles_several_simultaneously_new_alerts_into_one_notification(self):
        coord = self._make()
        coord._maybe_notify_new_alerts({"nearest": {"alerts": []}})

        coord._maybe_notify_new_alerts(
            {"nearest": {"alerts": [_alert("p1", "Corte C1"), _alert("p2", "Corte C2", lineas="C2")]}}
        )

        self.assertEqual(len(self._sent), 1)
        self.assertIn("Corte C1", self._sent[0]["message"])
        self.assertIn("Corte C2", self._sent[0]["message"])

    def test_deduplicates_the_same_alert_seen_across_multiple_stops(self):
        coord = self._make()
        coord._maybe_notify_new_alerts({"nearest": {"alerts": []}})

        shared_alert = _alert("p1", "Corte C1")
        coord._maybe_notify_new_alerts(
            {
                "nearest": {"alerts": [shared_alert]},
                "Urzaiz": {"alerts": [shared_alert]},
            }
        )

        self.assertEqual(len(self._sent), 1)
        self.assertEqual(self._sent[0]["title"], "VigoBus: nuevo aviso")

    def test_disabled_by_default_sends_nothing(self):
        coord = self._make(notify_new_alerts_enabled=False)
        coord._maybe_notify_new_alerts({"nearest": {"alerts": [_alert("p1", "Corte C1")]}})
        coord._maybe_notify_new_alerts(
            {"nearest": {"alerts": [_alert("p1", "Corte C1"), _alert("p2", "Corte C2")]}}
        )

        self.assertEqual(self._sent, [])


if __name__ == "__main__":
    unittest.main()
