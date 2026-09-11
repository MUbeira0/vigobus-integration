"""Real street-level walking directions via OpenRouteService (ORS).

No free, keyless, distribution-safe walking-routing service exists the way
OpenFreeMap solves that problem for map tiles (checked before adding this) —
OSRM's public demo server carries the same "not for production/redistributed
use" restriction that got this integration's map tiles blocked, and every
other free option requires an API key. ORS's free tier (2000 requests/day)
is generous enough for a personal trip planner, and — unlike a tile/geocoder
key shared across every install of a distributed app — each user gets their
own key for their own personal use, which is exactly what API key fair-use
terms expect. So this is opt-in: no key, no request, straight-line legs.

No Home Assistant import here (matches api.py/gtfs.py/geocoding.py), so this
stays testable as plain Python — only a duck-typed aiohttp-like session.
"""

import logging

_LOGGER = logging.getLogger(__name__)

ORS_DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/foot-walking/geojson"


async def get_walking_route(session, api_key, from_lat, from_lon, to_lat, to_lon, logger=None):
    """(from, to) coordinates -> [[lat, lon], ...] real walking path, or None
    when no api_key is configured or the request fails for any reason (a
    missing/expired/rate-limited key included) — callers fall back to a
    straight line between the two points, exactly like a bus leg with no
    GTFS shape already does.
    """
    log = logger or _LOGGER
    if not api_key:
        return None

    body = {"coordinates": [[from_lon, from_lat], [to_lon, to_lat]]}
    headers = {"Authorization": api_key, "Content-Type": "application/json"}

    try:
        async with session.post(ORS_DIRECTIONS_URL, json=body, headers=headers, timeout=10) as resp:
            if resp.status != 200:
                log.debug("VigoBus: ORS walking route request returned status %s", resp.status)
                return None
            data = await resp.json(content_type=None)
    except Exception as err:
        log.debug("VigoBus: ORS walking route request failed: %s", err)
        return None

    try:
        features = data.get("features") or []
        coordinates = features[0]["geometry"]["coordinates"]
    except (AttributeError, IndexError, KeyError, TypeError):
        return None

    points = []
    for pair in coordinates:
        try:
            lon, lat = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        points.append([lat, lon])

    return points if len(points) >= 2 else None
