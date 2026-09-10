"""Static GTFS feed for Vitrasa: download, parse, index, cache.

Vigo publishes an official GTFS feed (schedules/lines/stops) alongside the
other open-data files this integration already reads. It is what makes a
real trip planner (with transfers) possible without an external routing API.

GTFS stop_id here is the *municipal* stop id — the same value as paradas.json's
"stop_id" field, NOT its "id" field (the "vitrasa id" ESTIMACION_URL needs).
See api.get_estimacion()'s callers for that join when live data is needed.

This module is deliberately free of any Home Assistant import (like api.py)
so it stays testable as plain Python with no stubs required.
"""

import asyncio
import csv
import io
import logging
import time
import zipfile
from collections import defaultdict

from .api import haversine
from .const import GTFS_CACHE_TTL_SECONDS, GTFS_URL, TRIP_TRANSFER_CLUSTER_RADIUS_M

_LOGGER = logging.getLogger(__name__)

_GTFS_CACHE = {
    "expires_at": 0.0,
    "data": None,
}
_GTFS_LOCK = asyncio.Lock()


def _rows(zf, name):
    try:
        raw = zf.read(name)
    except KeyError:
        return []

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    return list(csv.DictReader(io.StringIO(text)))


def _parse_time(value):
    """"HH:MM:SS" -> seconds since midnight. GTFS allows HH >= 24 for trips
    that run past midnight — kept as-is (see the after-midnight limitation
    in the README: only services active on the query's own calendar date are
    considered, so a very-late-night query can miss a prior day's overflow
    trip)."""
    parts = str(value or "").strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = (int(p) for p in parts)
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


def _normalize_line(value):
    return str(value or "").strip().upper().replace(" ", "")


def _build_clusters(stops):
    """Group stops within TRIP_TRANSFER_CLUSTER_RADIUS_M of each other so a
    rider can transfer between e.g. opposite-direction platforms at one
    corner without a full walking-transfer graph. A coarse lat/lon grid keeps
    this from being an O(n^2) scan over ~1150 stops."""
    cell_size = 0.0006  # roughly ~65m at this latitude — coarser than the radius
    grid = defaultdict(list)
    for stop_id, stop in stops.items():
        cell = (round(stop["lat"] / cell_size), round(stop["lon"] / cell_size))
        grid[cell].append(stop_id)

    parent = {stop_id: stop_id for stop_id in stops}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for (cx, cy), members in grid.items():
        neighbor_ids = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbor_ids.extend(grid.get((cx + dx, cy + dy), ()))
        for stop_id in members:
            s = stops[stop_id]
            for other_id in neighbor_ids:
                if other_id == stop_id:
                    continue
                o = stops[other_id]
                if haversine(s["lat"], s["lon"], o["lat"], o["lon"]) <= TRIP_TRANSFER_CLUSTER_RADIUS_M:
                    union(stop_id, other_id)

    clusters = {stop_id: find(stop_id) for stop_id in stops}
    members_by_cluster = defaultdict(list)
    for stop_id, cluster_id in clusters.items():
        members_by_cluster[cluster_id].append(stop_id)

    return clusters, dict(members_by_cluster)


def parse_gtfs_zip(data, logger=None):
    """Pure, synchronous: bytes of the GTFS zip in, routing index dict out.

    Never touches the network or Home Assistant — this is what makes the
    routing engine unit-testable with a small synthetic fixture instead of
    the real ~17MB feed.
    """
    log = logger or _LOGGER
    start = time.monotonic()

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        if "frequencies.txt" in names:
            log.warning("VigoBus: GTFS feed now has frequencies.txt — currently ignored")

        stop_rows = _rows(zf, "stops.txt")
        route_rows = _rows(zf, "routes.txt")
        trip_rows = _rows(zf, "trips.txt")
        stop_time_rows = _rows(zf, "stop_times.txt")
        calendar_rows = _rows(zf, "calendar.txt")
        calendar_date_rows = _rows(zf, "calendar_dates.txt")
        # shapes.txt is deliberately never opened: it's only map polylines,
        # not needed for routing, and it's the largest file in the feed.

    stops = {}
    for row in stop_rows:
        stop_id = str(row.get("stop_id") or "").strip()
        if not stop_id:
            continue
        try:
            lat = float(row.get("stop_lat"))
            lon = float(row.get("stop_lon"))
        except (TypeError, ValueError):
            continue
        stops[stop_id] = {
            "name": str(row.get("stop_name") or "").strip() or stop_id,
            "lat": lat,
            "lon": lon,
        }

    routes = {}
    for row in route_rows:
        route_id = str(row.get("route_id") or "").strip()
        if not route_id:
            continue
        color = str(row.get("route_color") or "").strip()
        routes[route_id] = {
            "line": _normalize_line(row.get("route_short_name")),
            "long_name": str(row.get("route_long_name") or "").strip(),
            "color": f"#{color}" if color and color != "000000" else None,
        }

    trip_route = {}
    trip_headsign = {}
    for row in trip_rows:
        trip_id = str(row.get("trip_id") or "").strip()
        if not trip_id:
            continue
        trip_route[trip_id] = str(row.get("route_id") or "").strip()
        trip_headsign[trip_id] = str(row.get("trip_headsign") or "").strip()

    trip_service = {}
    for row in trip_rows:
        trip_id = str(row.get("trip_id") or "").strip()
        if trip_id:
            trip_service[trip_id] = str(row.get("service_id") or "").strip()

    stop_times_by_trip = defaultdict(list)
    for row in stop_time_rows:
        trip_id = str(row.get("trip_id") or "").strip()
        stop_id = str(row.get("stop_id") or "").strip()
        if not trip_id or stop_id not in stops:
            continue
        try:
            seq = int(row.get("stop_sequence"))
        except (TypeError, ValueError):
            continue
        arr = _parse_time(row.get("arrival_time"))
        dep = _parse_time(row.get("departure_time"))
        if arr is None or dep is None:
            continue
        stop_times_by_trip[trip_id].append((seq, arr, dep, stop_id))

    # Bucket trips into patterns: a pattern is (route_id, ordered stop_ids) —
    # RAPTOR's "route". Trips on the same physical line but a different stop
    # sequence (e.g. an early/late short-turn) get their own pattern.
    pattern_buckets = {}  # (route_id, stop_ids_tuple) -> list of trip_ids
    trip_stop_sequence = {}
    for trip_id, entries in stop_times_by_trip.items():
        entries.sort(key=lambda item: item[0])
        stop_ids = tuple(item[3] for item in entries)
        if len(stop_ids) < 2:
            continue
        trip_stop_sequence[trip_id] = entries
        route_id = trip_route.get(trip_id, "")
        key = (route_id, stop_ids)
        pattern_buckets.setdefault(key, []).append(trip_id)

    patterns = []
    routes_by_stop = defaultdict(list)
    for (route_id, stop_ids), trip_ids in pattern_buckets.items():
        trip_ids.sort(key=lambda tid: trip_stop_sequence[tid][0][2])  # by dep at stop 0
        n = len(stop_ids)
        m = len(trip_ids)
        dep = [[0] * m for _ in range(n)]
        arr = [[0] * m for _ in range(n)]
        for col, trip_id in enumerate(trip_ids):
            for row_idx, (_seq, a, d, _stop_id) in enumerate(trip_stop_sequence[trip_id]):
                arr[row_idx][col] = a
                dep[row_idx][col] = d

        pattern_idx = len(patterns)
        route_info = routes.get(route_id, {})
        patterns.append(
            {
                "route_id": route_id,
                "line": route_info.get("line") or "",
                "headsign": trip_headsign.get(trip_ids[0], ""),
                "stops": stop_ids,
                "trip_ids": trip_ids,
                "service_ids": [trip_service.get(tid, "") for tid in trip_ids],
                "dep": dep,
                "arr": arr,
            }
        )
        for i in range(n - 1):  # can't board at the terminus
            routes_by_stop[stop_ids[i]].append((pattern_idx, i))

    # calendar.txt (weekly patterns) — empty for this feed today, handled
    # anyway in case the publisher ever switches format.
    weekday_keys = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    calendar_rules = []
    for row in calendar_rows:
        service_id = str(row.get("service_id") or "").strip()
        if not service_id:
            continue
        try:
            start_date = str(row.get("start_date") or "").strip()
            end_date = str(row.get("end_date") or "").strip()
        except (TypeError, ValueError):
            continue
        weekdays = tuple(str(row.get(key) or "").strip() == "1" for key in weekday_keys)
        calendar_rules.append(
            {"service_id": service_id, "start": start_date, "end": end_date, "weekdays": weekdays}
        )

    added_dates = defaultdict(set)
    removed_dates = defaultdict(set)
    for row in calendar_date_rows:
        service_id = str(row.get("service_id") or "").strip()
        date_str = str(row.get("date") or "").strip()
        if not service_id or not date_str:
            continue
        exception_type = str(row.get("exception_type") or "").strip()
        if exception_type == "1":
            added_dates[date_str].add(service_id)
        elif exception_type == "2":
            removed_dates[date_str].add(service_id)

    clusters, cluster_members = _build_clusters(stops)

    index = {
        "stops": stops,
        "routes": routes,
        "patterns": patterns,
        "routes_by_stop": dict(routes_by_stop),
        "clusters": clusters,
        "cluster_members": cluster_members,
        "calendar_rules": calendar_rules,
        "added_dates": {k: frozenset(v) for k, v in added_dates.items()},
        "removed_dates": {k: frozenset(v) for k, v in removed_dates.items()},
        "_active_cache": {},
        "counts": {
            "stops": len(stops),
            "routes": len(routes),
            "trips": len(trip_route),
            "stop_times": len(stop_time_rows),
            "patterns": len(patterns),
        },
    }

    log.debug("VigoBus: parsed GTFS feed in %.2fs (%s)", time.monotonic() - start, index["counts"])
    return index


def active_services(index, date_str):
    cache = index.get("_active_cache")
    if cache is not None and date_str in cache:
        return cache[date_str]

    services = set()
    weekday = None
    if len(date_str) == 8:
        import datetime

        try:
            weekday = datetime.date(int(date_str[0:4]), int(date_str[4:6]), int(date_str[6:8])).weekday()
        except ValueError:
            weekday = None

    if weekday is not None:
        for rule in index.get("calendar_rules", ()):
            if rule["start"] <= date_str <= rule["end"] and rule["weekdays"][weekday]:
                services.add(rule["service_id"])

    services |= index.get("added_dates", {}).get(date_str, frozenset())
    services -= index.get("removed_dates", {}).get(date_str, frozenset())

    result = frozenset(services)
    if cache is not None:
        cache[date_str] = result
    return result


async def get_gtfs_index(session, logger=None, force=False):
    log = logger or _LOGGER
    now = time.monotonic()

    async with _GTFS_LOCK:
        if not force and _GTFS_CACHE["data"] is not None and now < _GTFS_CACHE["expires_at"]:
            return _GTFS_CACHE["data"]

        try:
            async with session.get(GTFS_URL, timeout=60) as resp:
                data = await resp.read()
            index = parse_gtfs_zip(data, logger=log)
        except Exception as err:
            if _GTFS_CACHE["data"] is not None:
                log.warning("VigoBus: unable to refresh GTFS feed, keeping previous index: %s", err)
                return _GTFS_CACHE["data"]
            raise

        _GTFS_CACHE["data"] = index
        _GTFS_CACHE["expires_at"] = now + GTFS_CACHE_TTL_SECONDS
        return index
