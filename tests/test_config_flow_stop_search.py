import asyncio
import importlib
import sys
import types
import unittest
from unittest.mock import patch


def _install_stubs():
    if "voluptuous" not in sys.modules:
        vol = types.ModuleType("voluptuous")
        vol.Optional = lambda *args, **kwargs: None
        vol.Required = lambda *args, **kwargs: None
        vol.All = lambda *args, **kwargs: None
        vol.Coerce = lambda *args, **kwargs: None
        vol.Range = lambda *args, **kwargs: None
        vol.In = lambda *args, **kwargs: None
        vol.Schema = lambda *args, **kwargs: None
        sys.modules["voluptuous"] = vol

    if "homeassistant" not in sys.modules:
        ha = types.ModuleType("homeassistant")
        config_entries = types.ModuleType("homeassistant.config_entries")

        class ConfigFlow:
            pass

        class OptionsFlow:
            def __init__(self, *args, **kwargs):
                self.hass = None

        config_entries.ConfigFlow = ConfigFlow
        config_entries.OptionsFlow = OptionsFlow

        helpers = types.ModuleType("homeassistant.helpers")
        aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")

        def async_get_clientsession(_hass):
            return object()

        aiohttp_client.async_get_clientsession = async_get_clientsession

        ha.config_entries = config_entries
        ha.helpers = helpers

        sys.modules["homeassistant"] = ha
        sys.modules["homeassistant.config_entries"] = config_entries
        sys.modules["homeassistant.helpers"] = helpers
        sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client


_install_stubs()
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
        self.assertEqual(stops, [{"id": "6930", "name": "Praza de America 1"}])

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
        self.assertEqual(stops, [{"id": "6930", "name": "Praza de America 1"}])

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


if __name__ == "__main__":
    unittest.main()
