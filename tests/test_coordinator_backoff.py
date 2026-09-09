import importlib
import unittest
from datetime import timedelta

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


class BackoffTests(unittest.TestCase):
    def _make(self, scan_interval=30):
        hass = _FakeHass()
        entry = _FakeEntry(data={"scan_interval": scan_interval})
        return coordinator_mod.VigoBusCoordinator(hass, entry)

    def test_no_backoff_below_threshold(self):
        coord = self._make(scan_interval=30)
        coord._consecutive_failures = coordinator_mod.BACKOFF_START_AFTER_FAILURES - 1
        coord._apply_backoff()
        self.assertEqual(coord.update_interval, timedelta(seconds=30))

    def test_backoff_doubles_starting_at_threshold(self):
        coord = self._make(scan_interval=30)
        coord._consecutive_failures = coordinator_mod.BACKOFF_START_AFTER_FAILURES
        coord._apply_backoff()
        self.assertEqual(coord.update_interval, timedelta(seconds=60))

        coord._consecutive_failures = coordinator_mod.BACKOFF_START_AFTER_FAILURES + 1
        coord._apply_backoff()
        self.assertEqual(coord.update_interval, timedelta(seconds=120))

    def test_backoff_is_capped(self):
        coord = self._make(scan_interval=30)
        coord._consecutive_failures = coordinator_mod.BACKOFF_START_AFTER_FAILURES + 20
        coord._apply_backoff()
        self.assertEqual(coord.update_interval, timedelta(seconds=coordinator_mod.BACKOFF_MAX_SECONDS))

    def test_success_resets_to_base_interval(self):
        coord = self._make(scan_interval=45)
        coord._consecutive_failures = coordinator_mod.BACKOFF_START_AFTER_FAILURES + 5
        coord._apply_backoff()
        self.assertNotEqual(coord.update_interval, timedelta(seconds=45))

        coord._consecutive_failures = 0
        coord._apply_backoff()
        self.assertEqual(coord.update_interval, timedelta(seconds=45))


if __name__ == "__main__":
    unittest.main()
