"""Free-text address/place search via OpenStreetMap's public Nominatim
instance, so the trip planner can search a real address or named place (a
school, a shopping mall) instead of only an exact bus stop.

No Home Assistant import here (matches api.py/gtfs.py), so this stays
testable as plain Python — only a duck-typed aiohttp-like session is needed.

Nominatim's usage policy (https://operations.osmfoundation.org/policies/nominatim/)
requires: a real, identifying User-Agent (NOMINATIM_USER_AGENT), at most
~1 request/second (enforced here via a module-level throttle), and that
results be attributed to OpenStreetMap contributors wherever they're shown.
"""

import asyncio
import logging
import time

from .const import (
    GEOCODE_CACHE_TTL_SECONDS,
    GEOCODE_VIEWBOX,
    NOMINATIM_MIN_INTERVAL_SECONDS,
    NOMINATIM_URL,
    NOMINATIM_USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

_GEOCODE_CACHE = {}
_THROTTLE_LOCK = asyncio.Lock()
_last_request_at = 0.0


def _cache_key(query, limit, lang):
    return (str(query or "").strip().lower(), int(limit), str(lang or "es").lower())


async def geocode(session, query, limit=5, lang="es", logger=None):
    """Free-text query -> list of {"name", "display_name", "latitude",
    "longitude"} dicts, best match first. Never raises for "no results" or
    a transient upstream failure — both just return an empty list, so a
    flaky geocoder can't break planning a trip to an already-known stop.
    """
    log = logger or _LOGGER
    query = str(query or "").strip()
    if not query:
        return []

    key = _cache_key(query, limit, lang)
    cached = _GEOCODE_CACHE.get(key)
    now = time.monotonic()
    if cached and now < cached[0]:
        return cached[1]

    global _last_request_at
    async with _THROTTLE_LOCK:
        wait = NOMINATIM_MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)

        params = {
            "format": "jsonv2",
            "q": query,
            "limit": str(limit),
            "viewbox": GEOCODE_VIEWBOX,
            "bounded": "1",
            "countrycodes": "es",
            "accept-language": lang,
        }
        headers = {"User-Agent": NOMINATIM_USER_AGENT}

        try:
            async with session.get(NOMINATIM_URL, params=params, headers=headers, timeout=10) as resp:
                data = await resp.json(content_type=None)
        except Exception as err:
            log.warning("VigoBus: geocoding lookup failed for %r: %s", query, err)
            return []
        finally:
            _last_request_at = time.monotonic()

    places = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                lat = float(item.get("lat"))
                lon = float(item.get("lon"))
            except (TypeError, ValueError):
                continue
            display_name = str(item.get("display_name") or "").strip()
            name = str(item.get("name") or "").strip() or display_name.split(",")[0].strip()
            if not name:
                continue
            places.append(
                {
                    "name": name,
                    "display_name": display_name or name,
                    "latitude": lat,
                    "longitude": lon,
                }
            )

    _GEOCODE_CACHE[key] = (now + GEOCODE_CACHE_TTL_SECONDS, places)
    return places
