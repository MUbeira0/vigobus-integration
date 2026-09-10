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


class _FakeServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, service_data=None, blocking=False):
        self.calls.append((domain, service, service_data or {}))


class _FakeHass:
    def __init__(self):
        self.states = _FakeStates()
        self.config = _FakeConfig()
        self.services = _FakeServices()


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


class NewAlertNotificationTests(unittest.IsolatedAsyncioTestCase):
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

    def _make(self, notify_new_alerts_enabled=True, notify_targets=None):
        hass = _FakeHass()
        data = {"notify_new_alerts_enabled": notify_new_alerts_enabled}
        if notify_targets is not None:
            data["notify_targets"] = notify_targets
        entry = _FakeEntry(data=data)
        return coordinator_mod.VigoBusCoordinator(hass, entry)

    async def test_first_cycle_establishes_baseline_without_notifying(self):
        # A restart (or a fresh coordinator) should never announce every
        # already-active alert as "new" — only alerts that show up *after*
        # that first baseline cycle count as new.
        coord = self._make()
        results = {"nearest": {"alerts": [_alert("p1", "Corte C1")]}}

        await coord._maybe_notify_new_alerts(results)

        self.assertEqual(self._sent, [])
        self.assertTrue(coord._alerts_baseline_done)
        self.assertIn(("p1", "Corte C1", "2026-01-01", "2026-01-02"), coord._notified_alert_ids)

    async def test_notifies_once_for_an_alert_appearing_after_baseline(self):
        coord = self._make()
        await coord._maybe_notify_new_alerts({"nearest": {"alerts": [_alert("p1", "Corte C1")]}})

        await coord._maybe_notify_new_alerts(
            {"nearest": {"alerts": [_alert("p1", "Corte C1"), _alert("p2", "Corte C2", lineas="C2")]}}
        )

        self.assertEqual(len(self._sent), 1)
        self.assertIn("Corte C2", self._sent[0]["message"])
        self.assertNotIn("Corte C1", self._sent[0]["message"])

        # Same state again next cycle: no duplicate notification.
        await coord._maybe_notify_new_alerts(
            {"nearest": {"alerts": [_alert("p1", "Corte C1"), _alert("p2", "Corte C2", lineas="C2")]}}
        )
        self.assertEqual(len(self._sent), 1)

    async def test_bundles_several_simultaneously_new_alerts_into_one_notification(self):
        coord = self._make()
        await coord._maybe_notify_new_alerts({"nearest": {"alerts": []}})

        await coord._maybe_notify_new_alerts(
            {"nearest": {"alerts": [_alert("p1", "Corte C1"), _alert("p2", "Corte C2", lineas="C2")]}}
        )

        self.assertEqual(len(self._sent), 1)
        self.assertIn("Corte C1", self._sent[0]["message"])
        self.assertIn("Corte C2", self._sent[0]["message"])

    async def test_deduplicates_the_same_alert_seen_across_multiple_stops(self):
        coord = self._make()
        await coord._maybe_notify_new_alerts({"nearest": {"alerts": []}})

        shared_alert = _alert("p1", "Corte C1")
        await coord._maybe_notify_new_alerts(
            {
                "nearest": {"alerts": [shared_alert]},
                "Urzaiz": {"alerts": [shared_alert]},
            }
        )

        self.assertEqual(len(self._sent), 1)
        self.assertEqual(self._sent[0]["title"], "VigoBus: nuevo aviso")

    async def test_disabled_by_default_sends_nothing(self):
        coord = self._make(notify_new_alerts_enabled=False)
        await coord._maybe_notify_new_alerts({"nearest": {"alerts": [_alert("p1", "Corte C1")]}})
        await coord._maybe_notify_new_alerts(
            {"nearest": {"alerts": [_alert("p1", "Corte C1"), _alert("p2", "Corte C2")]}}
        )

        self.assertEqual(self._sent, [])

    async def test_dispatch_calls_legacy_notify_service_for_a_plain_target_name(self):
        coord = self._make(notify_targets=["mobile_app_my_phone"])

        await coord._dispatch_notification("Title", "Message", "notif_id")

        self.assertEqual(len(self._sent), 1)
        self.assertEqual(
            coord.hass.services.calls,
            [("notify", "mobile_app_my_phone", {"title": "Title", "message": "Message"})],
        )

    async def test_dispatch_calls_send_message_for_an_entity_style_target(self):
        coord = self._make(notify_targets=["notify.my_phone"])

        await coord._dispatch_notification("Title", "Message", "notif_id")

        self.assertEqual(
            coord.hass.services.calls,
            [
                (
                    "notify",
                    "send_message",
                    {"entity_id": "notify.my_phone", "title": "Title", "message": "Message"},
                )
            ],
        )

    async def test_dispatch_with_no_targets_only_creates_the_persistent_notification(self):
        coord = self._make()

        await coord._dispatch_notification("Title", "Message", "notif_id")

        self.assertEqual(len(self._sent), 1)
        self.assertEqual(coord.hass.services.calls, [])

    async def test_dispatch_survives_one_target_failing(self):
        coord = self._make(notify_targets=["broken_target", "mobile_app_my_phone"])

        async def _raise(*args, **kwargs):
            raise RuntimeError("boom")

        # Only the first call (for "broken_target") should fail; patch
        # async_call so exactly that happens, then confirm the second
        # target still went through instead of the whole dispatch bailing.
        original_call = coord.hass.services.async_call
        calls = []

        async def _flaky(domain, service, service_data=None, blocking=False):
            calls.append((domain, service, service_data or {}))
            if service == "broken_target":
                raise RuntimeError("boom")
            return await original_call(domain, service, service_data, blocking)

        coord.hass.services.async_call = _flaky

        await coord._dispatch_notification("Title", "Message", "notif_id")

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(self._sent), 1)


if __name__ == "__main__":
    unittest.main()
