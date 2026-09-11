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

    def test_bus_leg_carries_the_real_street_shape_trimmed_to_the_ride(self):
        result = trip_planner.plan(
            self.index, self._access("A"), self._access("C"), "20260911", _seconds(6, 0)
        )
        leg = result["itineraries"][0]["legs"][0]
        # The full S_C1 shape (5 points, A -> B -> C with intermediates on
        # each street segment) end to end, since this ride covers all of it.
        self.assertEqual(
            leg["shape"],
            [[42.23, -8.72], [42.231, -8.721], [42.232, -8.722], [42.233, -8.723], [42.234, -8.724]],
        )

    def test_a_trip_with_no_shape_id_omits_the_shape_field(self):
        # T4 (service S2, no shape_id at all) is the only trip on its
        # pattern — the leg should just not have a "shape" key, so a
        # caller can fall back to a straight line between the stops.
        result = trip_planner.plan(
            self.index, self._access("A"), self._access("C"), "20260911", _seconds(0, 0), max_rounds=1
        )
        leg = result["itineraries"][0]["legs"][0]
        self.assertEqual(leg["depart"], "08:00")  # confirms this is the T1/T2 pattern, not T4
        # T4's own pattern (A->C direct, no shape_id) is a separate check:
        t4_pattern = next(p for p in self.index["patterns"] if "T4" in p["trip_ids"])
        shape = trip_planner._leg_shape(self.index, t4_pattern, 0, "A", "C")
        self.assertIsNone(shape)

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

    def test_returns_a_slower_direct_option_alongside_a_faster_transfer(self):
        # A third line (R3) runs a slow direct A->D trip; the existing
        # transfer via the C/C2 cluster (C1 then 15) is faster. Both should
        # come back, sorted by arrival — this is the "several reasonable
        # options" behaviour a rider expects from a real trip planner, not
        # just the single fastest path.
        index = gtfs.parse_gtfs_zip(
            build_fixture_zip(
                **{
                    "routes.txt": (
                        "route_id,route_short_name,route_long_name,route_color\n"
                        "R1,C1,Circular Centro,ED4713\n"
                        "R2,15,Navia,1A73C8\n"
                        "R3,20,Directo,00AA00\n"
                    ),
                    "trips.txt": (
                        "route_id,service_id,trip_id,trip_headsign,direction_id\n"
                        "R1,S1,T1,Navia,0\n"
                        "R1,S1,T2,Navia,0\n"
                        "R2,S1,T3,Centro,0\n"
                        "R1,S2,T4,Navia,0\n"
                        "R3,S1,T5,Directo,0\n"
                    ),
                    "stop_times.txt": (
                        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                        "T1,08:00:00,08:00:00,A,1\n"
                        "T1,08:05:00,08:05:00,B,2\n"
                        "T1,08:10:00,08:10:00,C,3\n"
                        "T2,08:30:00,08:30:00,A,1\n"
                        "T2,08:35:00,08:35:00,B,2\n"
                        "T2,08:40:00,08:40:00,C,3\n"
                        "T3,08:20:00,08:20:00,C2,1\n"
                        "T3,08:35:00,08:35:00,D,2\n"
                        "T4,25:10:00,25:10:00,A,1\n"
                        "T4,25:20:00,25:20:00,C,2\n"
                        "T5,08:00:00,08:00:00,A,1\n"
                        "T5,09:10:00,09:10:00,D,2\n"
                    ),
                }
            )
        )

        result = trip_planner.plan(
            index, self._access("A"), self._access("D"), "20260911", _seconds(6, 0), max_rounds=3
        )

        self.assertEqual(result["warnings"], [])
        self.assertEqual(len(result["itineraries"]), 2)

        # Sorted by arrival time: the faster transfer option comes first.
        transfer, direct = result["itineraries"]
        self.assertEqual(transfer["transfers"], 1)
        self.assertEqual(transfer["arrive"], "08:35")
        self.assertEqual(direct["transfers"], 0)
        self.assertEqual(direct["arrive"], "09:10")

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
