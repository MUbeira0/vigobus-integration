import importlib
import unittest

import conftest  # noqa: F401  (installs Home Assistant stubs on import)

diagnostics = importlib.import_module("custom_components.vigobus.diagnostics")
from custom_components.vigobus.const import DOMAIN  # noqa: E402


class _FakeCoordinator:
    def __init__(self, data):
        self.data = data
        self._last_success_at = "2026-01-01T00:00:00+00:00"
        self._last_error_at = None
        self._consecutive_failures = 0
        from datetime import timedelta

        self.update_interval = timedelta(seconds=30)


class _FakeEntry:
    def __init__(self, data, options=None):
        self.data = data
        self.options = options or {}
        self.entry_id = "test_entry"


class _FakeHass:
    def __init__(self, coordinator):
        self.data = {DOMAIN: {"test_entry": coordinator}}


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_redacts_sensitive_entry_fields(self):
        entry = _FakeEntry(
            data={
                "nearest_name": "Casa de la abuela",
                "extra_stops": [{"id": "1234", "name": "Trabajo", "line": ""}],
            }
        )
        coordinator = _FakeCoordinator(data={})
        hass = _FakeHass(coordinator)

        result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

        self.assertEqual(result["entry_data"]["nearest_name"], "**REDACTED**")
        self.assertEqual(result["entry_data"]["extra_stops"][0]["name"], "**REDACTED**")
        self.assertEqual(result["entry_data"]["extra_stops"][0]["id"], "1234")

    async def test_summarizes_stop_state_without_leaking_coordinates(self):
        entry = _FakeEntry(data={})
        coordinator = _FakeCoordinator(
            data={
                "nearest": {
                    "stale": False,
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "alerts_count": 0,
                    "data": {"estimaciones": [{"linea": "C1"}, {"linea": "9B"}]},
                }
            }
        )
        hass = _FakeHass(coordinator)

        result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

        self.assertEqual(result["coordinator"]["stops"]["nearest"]["bus_count"], 2)
        self.assertEqual(result["coordinator"]["update_interval_seconds"], 30)
        self.assertNotIn("latitude", str(result))
        self.assertNotIn("longitude", str(result))


if __name__ == "__main__":
    unittest.main()
