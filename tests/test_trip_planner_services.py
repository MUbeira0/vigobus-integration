import datetime
import importlib
import unittest
from unittest.mock import patch

import conftest  # noqa: F401  (installs Home Assistant stubs on import)
from test_gtfs import build_fixture_zip

vigobus_pkg = importlib.import_module("custom_components.vigobus")
gtfs = importlib.import_module("custom_components.vigobus.gtfs")
homeassistant_exceptions = importlib.import_module("homeassistant.exceptions")


class _FakeServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, service_data=None, blocking=False):
        self.calls.append((domain, service, service_data or {}))


class _FakeHass:
    def __init__(self):
        self.services = _FakeServices()

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class SearchStopsHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_ranked_matches_with_both_id_spaces(self):
        catalog = [
            {
                "id": "6930",
                "stop_id": "3493",
                "name": "Praza de America 1",
                "id_norm": "6930",
                "name_norm": "praza de america 1",
                "id_aliases_norm": ["6930", "3493"],
                "lat": 42.22,
                "lon": -8.73,
            }
        ]

        async def fake_catalog(_hass, force_refresh=False):
            return catalog

        with patch.object(vigobus_pkg, "_get_catalog_stops", fake_catalog):
            result = await vigobus_pkg.search_stops_handler(_FakeHass(), {"query": "praza"})

        self.assertEqual(len(result["stops"]), 1)
        stop = result["stops"][0]
        self.assertEqual(stop["id"], "6930")
        self.assertEqual(stop["stop_id"], "3493")
        self.assertEqual(stop["latitude"], 42.22)

    async def test_no_match_returns_empty_list(self):
        async def fake_catalog(_hass, force_refresh=False):
            return []

        with patch.object(vigobus_pkg, "_get_catalog_stops", fake_catalog):
            result = await vigobus_pkg.search_stops_handler(_FakeHass(), {"query": "nowhere"})

        self.assertEqual(result["stops"], [])


class ResolveDepartTests(unittest.TestCase):
    def test_no_depart_at_uses_now(self):
        now = datetime.datetime(2026, 9, 11, 8, 30, 0)
        date_str, seconds = vigobus_pkg._resolve_depart(None, now)
        self.assertEqual(date_str, "20260911")
        self.assertEqual(seconds, 8 * 3600 + 30 * 60)

    def test_hh_mm_is_parsed(self):
        now = datetime.datetime(2026, 9, 11, 8, 30, 0)
        date_str, seconds = vigobus_pkg._resolve_depart("18:05", now)
        self.assertEqual(date_str, "20260911")
        self.assertEqual(seconds, 18 * 3600 + 5 * 60)

    def test_garbage_falls_back_to_now(self):
        now = datetime.datetime(2026, 9, 11, 8, 30, 0)
        date_str, seconds = vigobus_pkg._resolve_depart("not-a-time", now)
        self.assertEqual(seconds, 8 * 3600 + 30 * 60)


class _FakeApi:
    def __init__(self, paradas, estimaciones):
        self._paradas = paradas
        self._estimaciones = estimaciones

    async def get_paradas(self):
        return self._paradas

    def _extract_stops(self, data):
        return data

    async def get_estimacion(self, stop_id):
        return {"estimaciones": self._estimaciones.get(stop_id, [])}

    def _normalize_line(self, value):
        return str(value or "").strip().upper().replace(" ", "")


class AttachLiveFirstLegTests(unittest.IsolatedAsyncioTestCase):
    def _itinerary(self, depart_seconds=8 * 3600):
        return {
            "legs": [
                {
                    "mode": "bus",
                    "line": "C1",
                    "from_stop": {"stop_id": "3493"},
                    "depart_seconds": depart_seconds,
                }
            ]
        }

    async def test_attaches_live_data_when_a_matching_line_is_found(self):
        api = _FakeApi(
            paradas=[{"stop_id": "3493", "id": 6930}],
            estimaciones={6930: [{"linea": "C1", "minutos": "4", "metros": 300}]},
        )
        itinerary = self._itinerary(depart_seconds=8 * 3600 + 10 * 60)
        now_seconds = 8 * 3600

        await vigobus_pkg._attach_live_first_leg(api, itinerary, now_seconds)

        self.assertEqual(itinerary["legs"][0]["live"]["minutos"], 4)
        self.assertTrue(itinerary["legs"][0]["live"]["is_live"])

    async def test_scheduled_projection_is_not_marked_live(self):
        api = _FakeApi(
            paradas=[{"stop_id": "3493", "id": 6930}],
            estimaciones={6930: [{"linea": "C1", "minutos": "4", "metros": -1}]},
        )
        itinerary = self._itinerary(depart_seconds=8 * 3600 + 10 * 60)

        await vigobus_pkg._attach_live_first_leg(api, itinerary, 8 * 3600)

        self.assertFalse(itinerary["legs"][0]["live"]["is_live"])

    async def test_skips_when_departure_is_beyond_the_live_check_horizon(self):
        api = _FakeApi(
            paradas=[{"stop_id": "3493", "id": 6930}],
            estimaciones={6930: [{"linea": "C1", "minutos": "4", "metros": 300}]},
        )
        # 3 hours away — well beyond LIVE_CHECK_HORIZON_SECONDS (45 min).
        itinerary = self._itinerary(depart_seconds=11 * 3600)

        await vigobus_pkg._attach_live_first_leg(api, itinerary, 8 * 3600)

        self.assertNotIn("live", itinerary["legs"][0])

    async def test_no_matching_stop_leaves_the_leg_untouched(self):
        api = _FakeApi(paradas=[{"stop_id": "9999", "id": 1}], estimaciones={})
        itinerary = self._itinerary()

        await vigobus_pkg._attach_live_first_leg(api, itinerary, 8 * 3600)

        self.assertNotIn("live", itinerary["legs"][0])


class PlanTripHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_an_origin(self):
        with self.assertRaises(homeassistant_exceptions.ServiceValidationError):
            await vigobus_pkg.plan_trip_handler(
                _FakeHass(), {"destination_stop_id": "C"}
            )

    async def test_requires_a_destination(self):
        with self.assertRaises(homeassistant_exceptions.ServiceValidationError):
            await vigobus_pkg.plan_trip_handler(
                _FakeHass(), {"origin_stop_id": "A"}
            )

    async def test_plans_a_direct_trip_between_two_explicit_stops(self):
        index = gtfs.parse_gtfs_zip(build_fixture_zip())

        async def fake_get_gtfs_index(session, logger=None, force=False):
            return index

        with patch.object(vigobus_pkg.gtfs, "get_gtfs_index", fake_get_gtfs_index):
            result = await vigobus_pkg.plan_trip_handler(
                _FakeHass(),
                {
                    "origin_stop_id": "A",
                    "destination_stop_id": "C",
                    "depart_at": "06:00",
                    "include_live": False,
                },
            )

        self.assertEqual(result["service_date"], datetime.datetime.now().strftime("%Y%m%d"))
        self.assertEqual(len(result["itineraries"]), 1)
        leg = result["itineraries"][0]["legs"][0]
        self.assertEqual(leg["line"], "C1")
        self.assertEqual(leg["depart"], "08:00")


if __name__ == "__main__":
    unittest.main()
