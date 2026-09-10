"""Pure RAPTOR-style trip planning over a parsed GTFS index (see gtfs.py).

No network, no Home Assistant, no clock of its own — the caller resolves
wall-clock time into (date_str "YYYYMMDD", seconds_since_midnight) and back.
This is what keeps it unit-testable with a tiny synthetic feed.

Known, accepted v1 limitations (see README):
- Only the query's own calendar date's active services are considered (a
  very-late-night query can miss a prior day's after-midnight overflow trip).
- Transfers only happen at the same stop or within a small walkable cluster
  (gtfs.TRIP_TRANSFER_CLUSTER_RADIUS_M) — no general walking-transfer graph.
- Forward "depart at" planning only (no "arrive by").
- Static timetable only; no live positions are consulted here (callers may
  cross-check the first leg's live estimacion separately).
"""

from bisect import bisect_left

from .api import haversine
from .const import TRIP_TRANSFER_MIN_SECONDS, WALK_SPEED_MPS
from .gtfs import active_services

INF = float("inf")


def nearest_index_stops(index, lat, lon, max_walk_m, limit=8):
    """Every GTFS stop within max_walk_m of (lat, lon), nearest first."""
    candidates = []
    for stop_id, stop in index["stops"].items():
        dist = haversine(lat, lon, stop["lat"], stop["lon"])
        if dist <= max_walk_m:
            candidates.append(
                {
                    "stop_id": stop_id,
                    "name": stop["name"],
                    "distance_m": round(dist, 1),
                    "walk_seconds": round(dist / WALK_SPEED_MPS),
                }
            )
    candidates.sort(key=lambda item: item["distance_m"])
    return candidates[:limit]


def _format_clock(seconds):
    seconds = int(seconds) % 86400
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"


def _cluster_neighbors(index, stop_id):
    cluster_id = index["clusters"].get(stop_id)
    if cluster_id is None:
        return ()
    return tuple(s for s in index["cluster_members"].get(cluster_id, ()) if s != stop_id)


def plan(index, origin_access, dest_access, date_str, depart_seconds, max_rounds=3, max_itineraries=3):
    """origin_access / dest_access: lists of {"stop_id", "walk_seconds", ...}
    from nearest_index_stops() (or a single {"stop_id", "walk_seconds": 0}
    when the caller already picked an exact stop).

    max_itineraries is accepted for a future multi-option version but v1
    always returns at most one (the fastest-arrival) itinerary — see the
    module docstring's limitations list.
    """
    services = active_services(index, date_str)
    if not services:
        return {"itineraries": [], "warnings": ["no_service_on_date"]}

    dest_walk = {a["stop_id"]: a["walk_seconds"] for a in dest_access if a["stop_id"] in index["stops"]}
    if not dest_walk:
        return {"itineraries": [], "warnings": ["no_route_found"]}

    origin_ids = {a["stop_id"] for a in origin_access}

    tau = {}
    tau_prev = {}
    labels = [dict() for _ in range(max_rounds + 1)]
    marked = set()

    for a in origin_access:
        stop_id = a["stop_id"]
        if stop_id not in index["stops"]:
            continue
        t = depart_seconds + a["walk_seconds"]
        if t < tau.get(stop_id, INF):
            tau[stop_id] = t
            tau_prev[stop_id] = t
            labels[0][stop_id] = {"kind": "origin", "walk_seconds": a["walk_seconds"]}
            marked.add(stop_id)

    best_target = INF
    for stop_id, walk_seconds in dest_walk.items():
        if stop_id in tau:
            best_target = min(best_target, tau[stop_id] + walk_seconds)

    for k in range(1, max_rounds + 1):
        queue = {}
        for stop_id in marked:
            for pattern_idx, stop_idx in index["routes_by_stop"].get(stop_id, ()):
                if pattern_idx not in queue or stop_idx < queue[pattern_idx]:
                    queue[pattern_idx] = stop_idx
        if not queue:
            break

        marked = set()
        for pattern_idx, start_idx in queue.items():
            pattern = index["patterns"][pattern_idx]
            stops = pattern["stops"]
            dep_cols = pattern["dep"]
            arr_cols = pattern["arr"]
            service_ids = pattern["service_ids"]
            n_trips = len(pattern["trip_ids"])

            trip = None
            board_idx = None
            board_stop = None

            for i in range(start_idx, len(stops)):
                stop_id = stops[i]

                if trip is not None:
                    arr_t = arr_cols[i][trip]
                    if arr_t < min(tau.get(stop_id, INF), best_target):
                        tau[stop_id] = arr_t
                        labels[k][stop_id] = {
                            "kind": "bus",
                            "pattern": pattern_idx,
                            "trip": trip,
                            "board_idx": board_idx,
                            "alight_idx": i,
                            "from_stop": board_stop,
                        }
                        marked.add(stop_id)
                        if stop_id in dest_walk:
                            best_target = min(best_target, arr_t + dest_walk[stop_id])

                ready = tau_prev.get(stop_id)
                if ready is None:
                    continue
                if not (stop_id in origin_ids and k == 1):
                    ready += TRIP_TRANSFER_MIN_SECONDS

                dep_col = dep_cols[i]
                if trip is not None and ready > dep_col[trip]:
                    continue
                j = bisect_left(dep_col, ready)
                while j < n_trips and service_ids[j] not in services:
                    j += 1
                if j < n_trips and (trip is None or j < trip):
                    trip, board_idx, board_stop = j, i, stop_id

        for stop_id in list(marked):
            for neighbor in _cluster_neighbors(index, stop_id):
                t = tau[stop_id] + TRIP_TRANSFER_MIN_SECONDS
                if t < tau.get(neighbor, INF):
                    tau[neighbor] = t
                    labels[k][neighbor] = {"kind": "cluster_walk", "from_stop": stop_id}
                    marked.add(neighbor)
                    if neighbor in dest_walk:
                        best_target = min(best_target, t + dest_walk[neighbor])

        tau_prev = dict(tau)
        if not marked:
            break

    best_stop = None
    best_arrival = INF
    for stop_id, walk_seconds in dest_walk.items():
        if stop_id in tau and tau[stop_id] + walk_seconds < best_arrival:
            best_arrival = tau[stop_id] + walk_seconds
            best_stop = stop_id

    if best_stop is None:
        return {"itineraries": [], "warnings": ["no_route_found"]}

    itinerary = _reconstruct(index, labels, max_rounds, best_stop, dest_walk, depart_seconds)
    if itinerary is None:
        return {"itineraries": [], "warnings": ["no_route_found"]}

    return {"itineraries": [itinerary], "warnings": []}


def _reconstruct(index, labels, max_round, best_stop, dest_walk, depart_seconds):
    # tau only improves over rounds, and every improvement is written
    # alongside a labels[k] entry, so the *highest* round index (searching
    # backward from max_round) holding a label for best_stop is the one
    # consistent with its final tau value.
    cursor = best_stop
    cursor_round = max_round
    while cursor_round > 0 and cursor not in labels[cursor_round]:
        cursor_round -= 1

    if cursor_round == 0:
        # Only reachable by the initial origin walk (no bus needed) — not a
        # trip worth planning.
        return None

    bus_legs = []
    while cursor_round > 0:
        label = labels[cursor_round].get(cursor)
        if label is None:
            cursor_round -= 1
            continue
        if label["kind"] == "cluster_walk":
            # Intra-round hop: the bus leg that reached the stop we just
            # walked from is *also* in this same round's labels, so don't
            # decrement cursor_round here or that leg would be skipped.
            cursor = label["from_stop"]
            continue
        if label["kind"] == "bus":
            bus_legs.append((cursor_round, cursor, label))
            cursor = label["from_stop"]
            cursor_round -= 1
            continue
        break
    bus_legs.reverse()

    if not bus_legs:
        return None

    legs = []
    origin_label = labels[0].get(cursor) or {"walk_seconds": 0}
    first_board_stop = bus_legs[0][2]["from_stop"]
    walk_seconds = origin_label.get("walk_seconds", 0)
    depart_at_origin = depart_seconds
    if walk_seconds:
        legs.append(
            {
                "mode": "walk",
                "to_stop": _stop_ref(index, first_board_stop),
                "distance_m": None,
                "duration_min": round(walk_seconds / 60, 1),
            }
        )

    last_arrival = None
    for _round_idx, alight_stop, label in bus_legs:
        pattern = index["patterns"][label["pattern"]]
        trip_idx = label["trip"]
        board_idx = label["board_idx"]
        alight_idx = label["alight_idx"]
        board_stop_id = pattern["stops"][board_idx]
        depart_t = pattern["dep"][board_idx][trip_idx]
        arrive_t = pattern["arr"][alight_idx][trip_idx]
        last_arrival = arrive_t
        legs.append(
            {
                "mode": "bus",
                "line": pattern["line"],
                "route_id": pattern["route_id"],
                "headsign": pattern["headsign"],
                "from_stop": _stop_ref(index, board_stop_id),
                "to_stop": _stop_ref(index, alight_stop),
                "depart": _format_clock(depart_t),
                "arrive": _format_clock(arrive_t),
                # Raw (possibly >86400, GTFS after-midnight convention)
                # seconds-since-midnight-of-the-service-day, alongside the
                # display strings above — callers comparing against "now"
                # need these instead of re-parsing the wrapped clock string.
                "depart_seconds": depart_t,
                "arrive_seconds": arrive_t,
                "duration_min": round((arrive_t - depart_t) / 60, 1),
                "num_stops": alight_idx - board_idx,
            }
        )

    last_stop = bus_legs[-1][1]
    dest_walk_seconds = dest_walk.get(last_stop, 0)
    if dest_walk_seconds:
        legs.append(
            {
                "mode": "walk",
                "from_stop": _stop_ref(index, last_stop),
                "distance_m": None,
                "duration_min": round(dest_walk_seconds / 60, 1),
            }
        )

    arrive_seconds = last_arrival + dest_walk_seconds
    lines = [leg["line"] for leg in legs if leg["mode"] == "bus"]
    total_walk_seconds = walk_seconds + dest_walk_seconds

    return {
        "depart": _format_clock(depart_at_origin),
        "arrive": _format_clock(arrive_seconds),
        "depart_seconds": depart_at_origin,
        "arrive_seconds": arrive_seconds,
        "duration_min": round((arrive_seconds - depart_at_origin) / 60),
        "transfers": max(0, len(bus_legs) - 1),
        "walk_min": round(total_walk_seconds / 60, 1) if total_walk_seconds else 0,
        "lines": lines,
        "legs": legs,
    }


def _stop_ref(index, stop_id):
    stop = index["stops"].get(stop_id, {})
    return {
        "stop_id": stop_id,
        "name": stop.get("name", stop_id),
        "latitude": stop.get("lat"),
        "longitude": stop.get("lon"),
    }


def attach_colors(result, line_colors):
    for itinerary in result.get("itineraries", []):
        for leg in itinerary.get("legs", []):
            if leg.get("mode") == "bus":
                leg["line_color"] = line_colors.get(leg["line"])
