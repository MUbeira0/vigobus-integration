import importlib
import unittest
from unittest.mock import patch

import conftest  # noqa: F401  (installs Home Assistant stubs on import)

config_flow = importlib.import_module("custom_components.vigobus.config_flow")


class ConfigFlowStopSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        config_flow._CATALOG_CACHE["data"] = []
        config_flow._CATALOG_CACHE["expires_at"] = 0.0

    def test_extract_catalog_stop_prioritizes_id(self):
        stop = {
            "id": 6930,
            "stop_id": "3493",
            "nombre": "Praza de America 1",
        }

        out = config_flow._extract_catalog_stop(stop)

        self.assertIsNotNone(out)
        self.assertEqual(out["id"], "6930")
        self.assertIn("6930", out["id_aliases"])
        self.assertIn("3493", out["id_aliases"])

    def test_search_prefers_exact_id(self):
        catalog = [
            {
                "id": "6930",
                "name": "Praza de America 1",
                "id_norm": "6930",
                "name_norm": "praza de america 1",
                "id_aliases_norm": ["6930", "3493"],
            },
            {
                "id": "3493",
                "name": "Otro",
                "id_norm": "3493",
                "name_norm": "otro",
                "id_aliases_norm": ["3493"],
            },
        ]

        match = config_flow._search_stop_by_text("6930", catalog)

        self.assertEqual(match, {"id": "6930", "name": "Praza de America 1"})

    async def test_parse_id_maps_alias_to_canonical_id(self):
        catalog = [
            {
                "id": "6930",
                "name": "Praza de America 1",
                "id_norm": "6930",
                "name_norm": "praza de america 1",
                "id_aliases_norm": ["6930", "3493"],
            }
        ]

        async def fake_catalog(_hass, force_refresh=False):
            return catalog

        with patch.object(config_flow, "_get_catalog_stops", fake_catalog):
            stops, has_errors = await config_flow._parse_extra_stops(object(), "3493")

        self.assertFalse(has_errors)
        self.assertEqual(stops, [{"id": "6930", "name": "Praza de America 1", "line": ""}])

    async def test_parse_search_uses_catalog_name_when_no_custom_name(self):
        catalog = [
            {
                "id": "6930",
                "name": "Praza de America 1",
                "id_norm": "6930",
                "name_norm": "praza de america 1",
                "id_aliases_norm": ["6930", "3493"],
            }
        ]

        async def fake_catalog(_hass, force_refresh=False):
            return catalog

        with patch.object(config_flow, "_get_catalog_stops", fake_catalog):
            stops, has_errors = await config_flow._parse_extra_stops(object(), "praza america")

        self.assertFalse(has_errors)
        self.assertEqual(stops, [{"id": "6930", "name": "Praza de America 1", "line": ""}])

    async def test_catalog_cache_reuses_previous_data_until_ttl(self):
        class FakeApi:
            calls = 0

            def __init__(self, _session):
                pass

            async def get_paradas(self):
                FakeApi.calls += 1
                return [{"id": 6930, "stop_id": "3493", "nombre": "Praza"}]

            def _extract_stops(self, data):
                return data

        with patch.object(config_flow, "VigoBusApi", FakeApi):
            first = await config_flow._get_catalog_stops(object(), force_refresh=False)
            second = await config_flow._get_catalog_stops(object(), force_refresh=False)

        self.assertEqual(FakeApi.calls, 1)
        self.assertEqual(first, second)


coordinator_mod = importlib.import_module("custom_components.vigobus.coordinator")


class _FakeState:
    def __init__(self, entity_id, state, attributes):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes


class _FakeStates:
    def __init__(self, states):
        self._by_id = {s.entity_id: s for s in states}

    def get(self, entity_id):
        return self._by_id.get(entity_id)

    def async_all(self, domain):
        prefix = f"{domain}."
        return [s for eid, s in self._by_id.items() if eid.startswith(prefix)]


class _FakeConfig:
    latitude = 42.2406
    longitude = -8.7207


class _FakeHass:
    def __init__(self, states):
        self.states = _FakeStates(states)
        self.config = _FakeConfig()


class _FakeEntry:
    def __init__(self, data=None, options=None):
        self.data = data or {}
        self.options = options or {}
        self.entry_id = "test_entry"


class NearestTargetsTests(unittest.TestCase):
    def _make(self, states, data=None, options=None):
        hass = _FakeHass(states)
        entry = _FakeEntry(data=data, options=options)
        return coordinator_mod.VigoBusCoordinator(hass, entry)

    def test_home_target_always_present(self):
        states = [_FakeState("zone.home", "zoning", {"latitude": 42.1, "longitude": -8.6})]
        coord = self._make(states, data={"auto_nearest": True})
        keys = [target[0] for target in coord._nearest_targets()]
        self.assertIn("nearest", keys)

    def test_explicit_device_is_added_without_removing_home(self):
        states = [
            _FakeState("zone.home", "zoning", {"latitude": 42.1, "longitude": -8.6}),
            _FakeState(
                "person.miguel",
                "home",
                {"latitude": 42.2, "longitude": -8.7, "friendly_name": "Miguel"},
            ),
        ]
        coord = self._make(
            states,
            data={"auto_nearest": True, "nearest_devices": ["person.miguel"]},
        )
        targets = {target[0]: target for target in coord._nearest_targets()}
        self.assertIn("nearest", targets)
        self.assertIn("nearest_person_miguel", targets)
        self.assertEqual(targets["nearest_person_miguel"][1], "Miguel")

    def test_auto_discovers_person_and_gps_tracker_only(self):
        states = [
            _FakeState(
                "person.ana",
                "home",
                {"latitude": 42.3, "longitude": -8.8, "friendly_name": "Ana"},
            ),
            _FakeState(
                "device_tracker.movil",
                "home",
                {"latitude": 42.4, "longitude": -8.9, "source_type": "gps"},
            ),
            _FakeState(
                "device_tracker.router",
                "home",
                {"latitude": 42.5, "longitude": -8.1, "source_type": "router"},
            ),
        ]
        coord = self._make(
            states,
            data={"auto_nearest": False, "auto_nearest_devices": True},
        )
        keys = {target[0] for target in coord._nearest_targets()}
        self.assertIn("nearest_person_ana", keys)
        self.assertIn("nearest_device_tracker_movil", keys)
        self.assertNotIn("nearest_device_tracker_router", keys)

    def test_device_without_coordinates_is_skipped(self):
        states = [_FakeState("person.sincoord", "home", {"friendly_name": "Sin"})]
        coord = self._make(
            states,
            data={"auto_nearest": False, "nearest_devices": ["person.sincoord"]},
        )
        self.assertEqual(coord._nearest_targets(), [])

    def test_unavailable_device_is_skipped(self):
        states = [
            _FakeState(
                "person.fuera",
                "unavailable",
                {"latitude": 42.2, "longitude": -8.7},
            )
        ]
        coord = self._make(
            states,
            data={"auto_nearest": False, "nearest_devices": ["person.fuera"]},
        )
        self.assertEqual(coord._nearest_targets(), [])

    def test_should_refresh_nearest_is_per_key(self):
        states = [_FakeState("zone.home", "zoning", {"latitude": 42.1, "longitude": -8.6})]
        coord = self._make(states, data={"auto_nearest": True})
        # No cache yet -> must refresh.
        self.assertTrue(coord._should_refresh_nearest("nearest", 42.1, -8.6))
        coord._closest_stops["nearest"] = {"id": "1"}
        coord._nearest_anchor["nearest"] = (42.1, -8.6)
        # Same spot for this key -> no refresh; a different key -> still refresh.
        self.assertFalse(coord._should_refresh_nearest("nearest", 42.1, -8.6))
        self.assertTrue(coord._should_refresh_nearest("nearest_person_x", 42.1, -8.6))


if __name__ == "__main__":
    unittest.main()
