import importlib
import unittest

import conftest  # noqa: F401  (installs Home Assistant stubs on import)

config_flow = importlib.import_module("custom_components.vigobus.config_flow")


class _FakeConfigEntry:
    def __init__(self, data=None, options=None):
        self.data = data or {}
        self.options = options or {}


class OptionsFlowSectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        config_flow._CATALOG_CACHE["data"] = []
        config_flow._CATALOG_CACHE["expires_at"] = 0.0

    def _flow(self):
        flow = config_flow.VigoBusOptionsFlow(_FakeConfigEntry())
        flow._ensure_draft()
        return flow

    async def test_edit_location_only_touches_its_own_keys(self):
        flow = self._flow()
        before_notify = dict(
            notify_enabled=flow._draft["notify_enabled"],
            notify_minutes=flow._draft["notify_minutes"],
        )

        await flow.async_step_edit_location(
            {
                "auto_nearest": False,
                "nearest_name": "Casa",
                "nearest_line_filter": "C1",
                "nearest_devices": ["person.miguel"],
                "auto_nearest_devices": True,
                "nearest_recalc_distance_m": 200,
                "scan_interval": 45,
            }
        )

        self.assertFalse(flow._draft["auto_nearest"])
        self.assertEqual(flow._draft["nearest_name"], "Casa")
        self.assertEqual(flow._draft["scan_interval"], 45)
        # Untouched by this step:
        self.assertEqual(flow._draft["notify_enabled"], before_notify["notify_enabled"])
        self.assertEqual(flow._draft["notify_minutes"], before_notify["notify_minutes"])

    async def test_edit_notifications_only_touches_its_own_keys(self):
        flow = self._flow()
        before_location = flow._draft["auto_nearest"]

        await flow.async_step_edit_notifications(
            {"notify_enabled": True, "notify_minutes": 3, "notify_cooldown_min": 10}
        )

        self.assertTrue(flow._draft["notify_enabled"])
        self.assertEqual(flow._draft["notify_minutes"], 3)
        self.assertEqual(flow._draft["notify_cooldown_min"], 10)
        self.assertEqual(flow._draft["auto_nearest"], before_location)

    async def test_edit_alerts_only_touches_its_own_keys(self):
        flow = self._flow()

        await flow.async_step_edit_alerts({"alerts_lang": "gl", "alerts_max_per_stop": 5})

        self.assertEqual(flow._draft["alerts_lang"], "gl")
        self.assertEqual(flow._draft["alerts_max_per_stop"], 5)

    async def test_edit_alerts_saves_notify_new_alerts_enabled(self):
        flow = self._flow()
        self.assertFalse(flow._draft["notify_new_alerts_enabled"])

        await flow.async_step_edit_alerts(
            {"alerts_lang": "es", "alerts_max_per_stop": 5, "notify_new_alerts_enabled": True}
        )

        self.assertTrue(flow._draft["notify_new_alerts_enabled"])

    async def test_init_menu_lists_the_split_sections(self):
        flow = self._flow()
        result = await flow.async_step_init()

        self.assertEqual(result["type"], "menu")
        self.assertIn("edit_location", result["menu_options"])
        self.assertIn("edit_notifications", result["menu_options"])
        self.assertIn("edit_alerts", result["menu_options"])
        self.assertIn("add_stops_bulk", result["menu_options"])
        self.assertNotIn("edit_general", result["menu_options"])


class BulkAddStopsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        config_flow._CATALOG_CACHE["data"] = []
        config_flow._CATALOG_CACHE["expires_at"] = 0.0

    def _flow(self):
        flow = config_flow.VigoBusOptionsFlow(_FakeConfigEntry())
        flow.hass = object()
        flow._ensure_draft()
        return flow

    async def test_bulk_add_appends_new_stops(self):
        flow = self._flow()

        await flow.async_step_add_stops_bulk({"extra_stops_bulk": "1234,Urzaiz,C1 | 5678,Colon"})

        ids = {stop["id"] for stop in flow._draft["extra_stops"]}
        self.assertEqual(ids, {"1234", "5678"})

    async def test_bulk_add_replaces_existing_id_instead_of_duplicating(self):
        flow = self._flow()
        flow._draft["extra_stops"] = [{"id": "1234", "name": "Old name", "line": ""}]

        await flow.async_step_add_stops_bulk({"extra_stops_bulk": "1234,New name,C1"})

        self.assertEqual(len(flow._draft["extra_stops"]), 1)
        self.assertEqual(flow._draft["extra_stops"][0]["name"], "New name")

    async def test_bulk_add_rejects_lines_missing_a_stop_id(self):
        flow = self._flow()

        result = await flow.async_step_add_stops_bulk({"extra_stops_bulk": ",Nombre sin id"})

        self.assertEqual(result["errors"]["base"], "invalid_extra_stops")


if __name__ == "__main__":
    unittest.main()
