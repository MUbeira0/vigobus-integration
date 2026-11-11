import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conftest  # noqa: E402,F401  (installs Home Assistant stubs on import)

coordinator_mod = importlib.import_module("custom_components.vigobus.coordinator")

from test_coordinator_alert_notifications import _alert, _FakeEntry, _FakeHass  # noqa: E402


def _stop(stop_id, lat=42.2265, lon=-8.6453, name=None):
    return {"id": stop_id, "stop_id": f"m{stop_id}", "latitud": lat, "longitud": lon, "nombre": name or f"Stop {stop_id}"}


def _buses(*lines):
    return {"estimaciones": [{"linea": line, "ruta": "R", "minutos": 4 + i, "metros": 100} for i, line in enumerate(lines)]}


class _FakeApi:
    def __init__(self, nearest, candidates, estimaciones, failing=()):
        self._nearest = nearest
        self._candidates = candidates
        self._estimaciones = estimaciones
        self._failing = set(failing)
        self.requested = []

    @staticmethod
    def haversine(lat1, lon1, lat2, lon2):
        return 0

    async def get_nearest_stop(self, lat, lon, logger=None):
        return self._nearest

    async def get_nearest_stops(self, lat, lon, margin_m=60, max_candidates=3, logger=None):
        self.margin_m = margin_m
        self.max_candidates = max_candidates
        return list(self._candidates)

    async def get_estimacion(self, stop_id):
        self.requested.append(str(stop_id))
        if str(stop_id) in self._failing:
            raise RuntimeError("boom")
        return self._estimaciones.get(str(stop_id), {"estimaciones": []})


class NearestFallbackTests(unittest.IsolatedAsyncioTestCase):
    def _coord(self, api):
        coord = coordinator_mod.VigoBusCoordinator(_FakeHass(), _FakeEntry(data={}))
        coord.api = api
        return coord

    async def _resolve(self, coord):
        return await coord._resolve_nearest_target("nearest", "Casa", 42.2265, -8.6453, "now", {})

    async def test_uses_the_closest_stop_when_it_has_buses(self):
        a, b = _stop("1"), _stop("2")
        api = _FakeApi(a, [a, b], {"1": _buses("C1")})
        entry = await self._resolve(self._coord(api))

        self.assertEqual(entry["stop"]["id"], "1")
        self.assertNotIn("fallback", entry)
        self.assertEqual(api.requested, ["1"])  # no extra requests when the closest stop has service

    async def test_falls_back_to_the_next_stop_with_buses(self):
        a, b, c = _stop("1"), _stop("2"), _stop("3")
        api = _FakeApi(a, [a, b, c], {"3": _buses("A", "C1")})
        entry = await self._resolve(self._coord(api))

        self.assertEqual(entry["stop"]["id"], "3")
        self.assertEqual(entry["stop_name"], "Casa")  # the sensor keeps its own name
        self.assertEqual(entry["fallback"], {"from_stop_id": "1", "stop_id": "3", "stop_name": "Stop 3"})
        self.assertEqual(len(entry["data"]["estimaciones"]), 2)
        self.assertEqual(api.requested, ["1", "2", "3"])  # closest first, then in distance order

    async def test_keeps_the_closest_stop_when_nothing_nearby_has_buses(self):
        a, b = _stop("1"), _stop("2")
        api = _FakeApi(a, [a, b], {})
        entry = await self._resolve(self._coord(api))

        self.assertEqual(entry["stop"]["id"], "1")
        self.assertNotIn("fallback", entry)

    async def test_a_failing_candidate_is_skipped(self):
        a, b, c = _stop("1"), _stop("2"), _stop("3")
        api = _FakeApi(a, [a, b, c], {"3": _buses("C1")}, failing=["2"])
        entry = await self._resolve(self._coord(api))

        self.assertEqual(entry["stop"]["id"], "3")

    async def test_the_anchor_stop_is_not_replaced_by_the_fallback(self):
        a, b = _stop("1"), _stop("2")
        api = _FakeApi(a, [a, b], {"2": _buses("C1")})
        coord = self._coord(api)

        await self._resolve(coord)

        # The closest stop stays the anchor, so the next scan tries it first again.
        self.assertEqual(coord._closest_stops["nearest"]["id"], "1")

    async def test_the_radius_option_sets_how_far_to_look(self):
        a = _stop("1")
        api = _FakeApi(a, [a], {})
        coord = coordinator_mod.VigoBusCoordinator(_FakeHass(), _FakeEntry(data={"nearest_fallback_radius_m": 800}))
        coord.api = api
        await self._resolve(coord)

        self.assertEqual(api.margin_m, 800)
        self.assertEqual(api.max_candidates, coordinator_mod.NEAREST_FALLBACK_MAX_CANDIDATES)

    async def test_default_radius_is_250_m(self):
        a = _stop("1")
        api = _FakeApi(a, [a], {})
        await self._resolve(self._coord(api))
        self.assertEqual(api.margin_m, 250)

    async def test_radius_zero_turns_the_fallback_off(self):
        a, b = _stop("1"), _stop("2")
        api = _FakeApi(a, [a, b], {"2": _buses("C1")})
        coord = coordinator_mod.VigoBusCoordinator(_FakeHass(), _FakeEntry(data={"nearest_fallback_radius_m": 0}))
        coord.api = api

        entry = await self._resolve(coord)

        self.assertEqual(entry["stop"]["id"], "1")
        self.assertFalse(hasattr(api, "margin_m"))  # candidates were never even requested
        self.assertEqual(api.requested, ["1"])

    async def test_a_search_that_found_nothing_is_not_repeated_right_away(self):
        a, b = _stop("1"), _stop("2")
        api = _FakeApi(a, [a, b], {})
        coord = self._coord(api)

        await self._resolve(coord)
        first = list(api.requested)
        await self._resolve(coord)

        # The second scan only re-checks the closest stop: no new candidate lookup.
        self.assertEqual(api.requested, first + ["1"])

    async def test_candidates_are_queried_together_and_the_closest_with_buses_wins(self):
        a, b, c = _stop("1"), _stop("2"), _stop("3")
        api = _FakeApi(a, [a, b, c], {"2": _buses("A"), "3": _buses("C1")})
        entry = await self._resolve(self._coord(api))

        self.assertEqual(entry["stop"]["id"], "2")


class NoServiceInfoTests(unittest.IsolatedAsyncioTestCase):
    def _coord(self):
        coord = coordinator_mod.VigoBusCoordinator(_FakeHass(), _FakeEntry(data={}))
        coord.hass.async_create_task = lambda coro: coro.close()
        return coord

    async def test_lists_the_lines_that_serve_the_stop_when_the_schedule_is_not_loaded(self):
        coord = self._coord()
        original = coordinator_mod.gtfs.cached_index
        coordinator_mod.gtfs.cached_index = lambda: None
        try:
            info = coord._no_service_info({"stop_id": "3816", "lineas": "25, 11"})
        finally:
            coordinator_mod.gtfs.cached_index = original
        self.assertEqual(info, {"serving_lines": ["25", "11"]})
        self.assertTrue(coord._gtfs_warm_requested)

    async def test_adds_the_next_scheduled_departure_when_the_schedule_is_loaded(self):
        coord = self._coord()
        original = (coordinator_mod.gtfs.cached_index, coordinator_mod.gtfs.next_departures)
        coordinator_mod.gtfs.cached_index = lambda: {"fake": True}
        coordinator_mod.gtfs.next_departures = lambda index, stop_id, date_str, seconds, limit=1: [
            {"seconds": 7 * 3600 + 10 * 60, "line": "25", "headsign": "CENTRO", "next_day": True}
        ]
        try:
            info = coord._no_service_info({"stop_id": "3816", "lineas": "25"})
        finally:
            coordinator_mod.gtfs.cached_index, coordinator_mod.gtfs.next_departures = original
        self.assertEqual(info["next_scheduled"], {"time": "07:10", "line": "25", "headsign": "CENTRO", "tomorrow": True})

    async def test_resolve_target_reports_no_service_when_nothing_nearby_has_buses(self):
        a = _stop("1")
        a["lineas"] = "25"
        api = _FakeApi(a, [a], {})
        coord = coordinator_mod.VigoBusCoordinator(_FakeHass(), _FakeEntry(data={}))
        coord.api = api
        coord.hass.async_create_task = lambda coro: coro.close()
        original = coordinator_mod.gtfs.cached_index
        coordinator_mod.gtfs.cached_index = lambda: None
        try:
            entry = await coord._resolve_nearest_target("nearest", "Casa", 42.2, -8.6, "now", {})
        finally:
            coordinator_mod.gtfs.cached_index = original
        self.assertEqual(entry["no_service"]["serving_lines"], ["25"])
        self.assertNotIn("fallback", entry)


class AlertCapOrderTests(unittest.TestCase):
    def _coord(self, **options):
        return coordinator_mod.VigoBusCoordinator(_FakeHass(), _FakeEntry(data=options))

    def test_alerts_in_force_are_never_cut_by_the_cap_in_favour_of_upcoming_ones(self):
        index = {
            "A": [
                _alert("f1", "Futuro 1", inicio="2998-01-01", fin="2999-01-01"),
                _alert("f2", "Futuro 2", inicio="2998-01-01", fin="2999-01-01"),
            ],
            "C1": [_alert("now", "En vigor", inicio="2000-01-01", fin="2999-01-01")],
        }
        result = {"data": {"estimaciones": [{"linea": "A"}, {"linea": "C1"}]}}

        out = self._coord(alerts_max_per_stop=2)._attach_alerts(result, index)

        self.assertEqual([a["id_publicacion"] for a in out["alerts"]], ["now", "f1"])
        self.assertEqual(out["alerts_count"], 1)

    def test_a_cap_below_one_still_keeps_one_alert(self):
        index = {"C1": [_alert("now", "En vigor", inicio="2000-01-01", fin="2999-01-01")]}
        out = self._coord(alerts_max_per_stop=0)._attach_alerts({"data": {"estimaciones": [{"linea": "C1"}]}}, index)
        self.assertEqual(len(out["alerts"]), 1)


if __name__ == "__main__":
    unittest.main()
