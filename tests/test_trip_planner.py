import importlib
import unittest

import conftest  # noqa: F401  (installs Home Assistant stubs on import)
from test_gtfs import build_fixture_zip

gtfs = importlib.import_module("custom_components.vigobus.gtfs")
trip_planner = importlib.import_module("custom_components.vigobus.trip_planner")


def _seconds(hh, mm):
    return hh * 3600 + mm * 60


class TripPlannerTests(unittest.TestCase):
    def setUp(self):
        self.index = gtfs.parse_gtfs_zip(build_fixture_zip())

    def _access(self, stop_id):
        return [{"stop_id": stop_id, "walk_seconds": 0}]

    def test_direct_trip_takes_the_earliest_catchable_bus(self):
        result = trip_planner.plan(
            self.index, self._access("A"), self._access("C"), "20260911", _seconds(6, 0)
        )
        self.assertEqual(result["warnings"], [])
        self.assertEqual(len(result["itineraries"]), 1)
        itinerary = result["itineraries"][0]
        self.assertEqual(itinerary["transfers"], 0)
        self.assertEqual(len(itinerary["legs"]), 1)
        leg = itinerary["legs"][0]
        self.assertEqual(leg["mode"], "bus")
        self.assertEqual(leg["line"], "C1")
        self.assertEqual(leg["depart"], "08:00")
        self.assertEqual(leg["arrive"], "08:10")

    def test_departing_mid_headway_takes_the_later_trip_not_a_departed_one(self):
        result = trip_planner.plan(
            self.index, self._access("A"), self._access("C"), "20260911", _seconds(8, 6)
        )
        leg = result["itineraries"][0]["legs"][0]
        self.assertEqual(leg["depart"], "08:30")
        self.assertEqual(leg["arrive"], "08:40")

    def test_transfer_via_the_stop_cluster(self):
        result = trip_planner.plan(
            self.index, self._access("A"), self._access("D"), "20260911", _seconds(6, 0), max_rounds=3
        )
        self.assertEqual(result["warnings"], [])
        itinerary = result["itineraries"][0]
        self.assertEqual(itinerary["transfers"], 1)
        bus_legs = [leg for leg in itinerary["legs"] if leg["mode"] == "bus"]
        self.assertEqual(len(bus_legs), 2)
        self.assertEqual(bus_legs[0]["line"], "C1")
        self.assertEqual(bus_legs[0]["arrive"], "08:10")
        self.assertEqual(bus_legs[1]["line"], "15")
        self.assertEqual(bus_legs[1]["depart"], "08:20")
        self.assertEqual(bus_legs[1]["arrive"], "08:35")
        self.assertEqual(itinerary["arrive"], "08:35")

    def test_unreachable_destination_reports_no_route_found(self):
        result = trip_planner.plan(
            self.index, self._access("A"), self._access("Z"), "20260911", _seconds(6, 0)
        )
        self.assertEqual(result["itineraries"], [])
        self.assertEqual(result["warnings"], ["no_route_found"])

    def test_zero_transfers_budget_cannot_reach_a_stop_needing_one(self):
        result = trip_planner.plan(
            self.index, self._access("A"), self._access("D"), "20260911", _seconds(6, 0), max_rounds=1
        )
        self.assertEqual(result["itineraries"], [])

    def test_max_walk_m_filters_out_a_far_origin(self):
        # Z's coordinates are far from every other stop in the fixture.
        far_lat, far_lon = self.index["stops"]["Z"]["lat"], self.index["stops"]["Z"]["lon"]
        access = trip_planner.nearest_index_stops(self.index, far_lat, far_lon, max_walk_m=50)
        self.assertEqual([a["stop_id"] for a in access], ["Z"])

        near_a_lat, near_a_lon = self.index["stops"]["A"]["lat"], self.index["stops"]["A"]["lon"]
        access = trip_planner.nearest_index_stops(self.index, near_a_lat, near_a_lon, max_walk_m=10)
        self.assertEqual([a["stop_id"] for a in access], ["A"])

    def test_removed_service_excludes_that_days_trip(self):
        # T4 (service S2, direct A->C) is removed on the 12th, but T1/T2
        # (service S1, via B) still run — the direct-only pattern for T4
        # should simply have no active trips that day.
        result_11 = trip_planner.plan(
            self.index, self._access("A"), self._access("C"), "20260912", _seconds(0, 0), max_rounds=1
        )
        # Only S1 trips remain reachable from a 00:00 departure that day.
        leg = result_11["itineraries"][0]["legs"][0]
        self.assertEqual(leg["depart"], "08:00")


if __name__ == "__main__":
    unittest.main()
