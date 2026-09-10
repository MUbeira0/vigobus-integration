import importlib
import io
import unittest
import zipfile

import conftest  # noqa: F401  (installs Home Assistant stubs on import)

gtfs = importlib.import_module("custom_components.vigobus.gtfs")


def build_fixture_zip(**overrides):
    """A tiny, hand-written synthetic GTFS feed exercising every code path
    the real ~17MB Vitrasa feed does, without committing a binary fixture.

    Layout: A -[C1]-> B -[C1]-> C  (two C1 trips, T1 early / T2 later)
            C2 -[15]-> D            (one 15 trip, T3)
            C and C2 are ~3m apart -> should merge into one transfer cluster.
            Z is far away and served by nothing -> unreachable.
            T4 (route C1, service S2, direct A->C) uses a >24h time to
            exercise the post-midnight parse; S2 is removed on the 12th.
    """
    files = {
        "agency.txt": (
            "agency_id,agency_name,agency_url,agency_timezone\n"
            "1,Vitrasa,http://x,Europe/Madrid\n"
        ),
        "routes.txt": (
            "route_id,route_short_name,route_long_name,route_color\n"
            "R1,C1,Circular Centro,ED4713\n"
            "R2,15,Navia,1A73C8\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id,trip_headsign,direction_id\n"
            "R1,S1,T1,Navia,0\n"
            "R1,S1,T2,Navia,0\n"
            "R2,S1,T3,Centro,0\n"
            "R1,S2,T4,Navia,0\n"
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
        ),
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,Origen,42.2300,-8.7200\n"
            "B,Media,42.2320,-8.7220\n"
            "C,Transbordo,42.2340,-8.7240\n"
            "C2,Transbordo (impar),42.23403,-8.72403\n"
            "D,Destino,42.2400,-8.7300\n"
            "Z,Aislada,42.3000,-8.9000\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
            "start_date,end_date\n"
        ),
        "calendar_dates.txt": (
            "service_id,date,exception_type\n"
            "S1,20260911,1\n"
            "S2,20260911,1\n"
            "S1,20260912,1\n"
            "S2,20260912,2\n"
        ),
        "shapes.txt": "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\nX,0,0,1\n",
    }
    files.update(overrides)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


class GtfsParseTests(unittest.TestCase):
    def test_counts_match_the_fixture(self):
        index = gtfs.parse_gtfs_zip(build_fixture_zip())
        self.assertEqual(index["counts"]["stops"], 6)
        self.assertEqual(index["counts"]["routes"], 2)
        self.assertEqual(index["counts"]["trips"], 4)
        self.assertEqual(index["counts"]["stop_times"], 10)
        # T1/T2 share (route, stop-sequence) -> one pattern; T3 -> another;
        # T4 has a different stop sequence (A->C direct) -> its own pattern.
        self.assertEqual(index["counts"]["patterns"], 3)

    def test_shapes_txt_is_never_opened(self):
        # A malformed shapes.txt must not break parsing, proving it's unread.
        index = gtfs.parse_gtfs_zip(build_fixture_zip(**{"shapes.txt": "not,even,csv,{{{"}))
        self.assertEqual(index["counts"]["stops"], 6)

    def test_handles_utf8_bom(self):
        with_bom = build_fixture_zip()
        # Re-zip stops.txt with a BOM to exercise the utf-8-sig decode path.
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(with_bom)) as src, zipfile.ZipFile(buf, "w") as dst:
            for name in src.namelist():
                data = src.read(name)
                if name == "stops.txt":
                    data = b"\xef\xbb\xbf" + data
                dst.writestr(name, data)
        index = gtfs.parse_gtfs_zip(buf.getvalue())
        self.assertEqual(index["counts"]["stops"], 6)
        self.assertIn("A", index["stops"])

    def test_tolerates_a_missing_calendar_file(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(build_fixture_zip())) as src, zipfile.ZipFile(buf, "w") as dst:
            for name in src.namelist():
                if name == "calendar.txt":
                    continue
                dst.writestr(name, src.read(name))
        index = gtfs.parse_gtfs_zip(buf.getvalue())
        self.assertEqual(index["calendar_rules"], [])

    def test_pattern_time_parsing_allows_hours_past_24(self):
        index = gtfs.parse_gtfs_zip(build_fixture_zip())
        t4_pattern = next(p for p in index["patterns"] if "T4" in p["trip_ids"])
        col = t4_pattern["trip_ids"].index("T4")
        self.assertEqual(t4_pattern["dep"][0][col], 25 * 3600 + 10 * 60)

    def test_trips_within_a_pattern_are_sorted_by_departure(self):
        index = gtfs.parse_gtfs_zip(build_fixture_zip())
        abc_pattern = next(p for p in index["patterns"] if p["stops"] == ("A", "B", "C"))
        self.assertEqual(abc_pattern["trip_ids"], ["T1", "T2"])

    def test_routes_by_stop_excludes_the_terminus(self):
        index = gtfs.parse_gtfs_zip(build_fixture_zip())
        abc_pattern_idx = next(
            i for i, p in enumerate(index["patterns"]) if p["stops"] == ("A", "B", "C")
        )
        entries_at_c = [e for e in index["routes_by_stop"].get("C", ()) if e[0] == abc_pattern_idx]
        self.assertEqual(entries_at_c, [])
        entries_at_a = [e for e in index["routes_by_stop"].get("A", ()) if e[0] == abc_pattern_idx]
        self.assertEqual(entries_at_a, [(abc_pattern_idx, 0)])

    def test_nearby_stops_are_merged_into_one_cluster(self):
        index = gtfs.parse_gtfs_zip(build_fixture_zip())
        self.assertEqual(index["clusters"]["C"], index["clusters"]["C2"])

    def test_far_stops_are_not_merged(self):
        index = gtfs.parse_gtfs_zip(build_fixture_zip())
        self.assertNotEqual(index["clusters"]["C"], index["clusters"]["Z"])

    def test_route_color_is_normalized_to_a_hex_string(self):
        index = gtfs.parse_gtfs_zip(build_fixture_zip())
        self.assertEqual(index["routes"]["R1"]["color"], "#ED4713")
        self.assertEqual(index["routes"]["R1"]["line"], "C1")


class ActiveServicesTests(unittest.TestCase):
    def setUp(self):
        self.index = gtfs.parse_gtfs_zip(build_fixture_zip())

    def test_both_services_active_on_the_11th(self):
        services = gtfs.active_services(self.index, "20260911")
        self.assertIn("S1", services)
        self.assertIn("S2", services)

    def test_s2_is_removed_on_the_12th(self):
        services = gtfs.active_services(self.index, "20260912")
        self.assertIn("S1", services)
        self.assertNotIn("S2", services)

    def test_unknown_date_has_no_active_services(self):
        services = gtfs.active_services(self.index, "20200101")
        self.assertEqual(services, frozenset())


if __name__ == "__main__":
    unittest.main()
