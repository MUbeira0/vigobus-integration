"""Stop name/id search, shared by the config-flow "add stop" search step and
the stateless search_stops service the card calls for the trip planner.

Factored out of config_flow.py (rather than imported from there) because
config_flow.py is loaded lazily by Home Assistant — only when a user opens
the integration's config/options flow — and pulling it in from __init__.py
just to reach this matcher would force the whole options-flow module (plus
homeassistant.helpers.selector) into memory at every startup, for every
user, including ones who never touch the planner.
"""

import time
import unicodedata

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VigoBusApi

CATALOG_CACHE_TTL_SECONDS = 15 * 60
_CATALOG_CACHE = {
    "expires_at": 0.0,
    "data": [],
}


def _normalize_text(value):
    text = str(value or "").strip().lower()
    normalized = unicodedata.normalize("NFD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _extract_catalog_stop(stop):
    if not isinstance(stop, dict):
        return None

    properties = stop.get("properties") if isinstance(stop.get("properties"), dict) else {}

    ids_by_key = {}
    for key in ("stop_id", "idparada", "parada", "id"):
        value = stop.get(key)
        if value is None:
            value = properties.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            ids_by_key[key] = text

    stop_id = None
    for key in ("id", "stop_id", "idparada", "parada"):
        if key in ids_by_key:
            stop_id = ids_by_key[key]
            break

    if not stop_id:
        return None

    name = None
    for key in ("nombre", "name", "denominacion", "title", "descripcion", "label", "parada"):
        value = stop.get(key)
        if value is None:
            value = properties.get(key)
        if value is not None and str(value).strip():
            name = str(value).strip()
            break

    if not name:
        name = f"stop_{stop_id}"

    aliases = []
    for key in ("id", "stop_id", "idparada", "parada"):
        value = ids_by_key.get(key)
        if value and value not in aliases:
            aliases.append(value)

    try:
        lat = float(stop.get("lat"))
        lon = float(stop.get("lon"))
    except (TypeError, ValueError):
        lat = None
        lon = None

    return {
        "id": stop_id,
        "name": name,
        "id_norm": _normalize_text(stop_id),
        "name_norm": _normalize_text(name),
        "id_aliases": aliases,
        "id_aliases_norm": [_normalize_text(item) for item in aliases],
        # GTFS/municipal stop id — different id-space from "id" (the
        # "vitrasa id" ESTIMACION_URL needs). The trip planner works in this
        # space; live-arrival lookups need "id" instead.
        "stop_id": ids_by_key.get("stop_id"),
        "lat": lat,
        "lon": lon,
    }


def _search_stop_by_text(query, catalog):
    query_norm = _normalize_text(query)
    if not query_norm:
        return None

    terms = [term for term in query_norm.split() if term]
    best = None
    best_score = None

    for stop in catalog:
        id_norm = stop["id_norm"]
        id_aliases_norm = stop.get("id_aliases_norm", [id_norm])
        name_norm = stop["name_norm"]

        score = None
        if query_norm == id_norm:
            score = 0
        elif query_norm in id_aliases_norm:
            score = 1
        elif any(alias.startswith(query_norm) for alias in id_aliases_norm):
            score = 5
        elif query_norm == name_norm:
            score = 1
        elif query_norm in name_norm:
            score = 10 + len(name_norm)
        elif terms and all(term in name_norm for term in terms):
            score = 20 + len(name_norm)

        if score is None:
            continue

        if best is None or score < best_score:
            best = stop
            best_score = score

    if best is None:
        return None

    return {"id": best["id"], "name": best["name"]}


def search_stops_ranked(query, catalog, limit=8):
    """Every catalog stop matching query, best match first (for the card's
    destination search — unlike _search_stop_by_text, which only needs the
    single best match for the config-flow "add stop" step)."""
    query_norm = _normalize_text(query)
    if not query_norm:
        return []

    terms = [term for term in query_norm.split() if term]
    scored = []
    for stop in catalog:
        id_norm = stop["id_norm"]
        id_aliases_norm = stop.get("id_aliases_norm", [id_norm])
        name_norm = stop["name_norm"]

        score = None
        if query_norm == id_norm:
            score = 0
        elif query_norm in id_aliases_norm:
            score = 1
        elif any(alias.startswith(query_norm) for alias in id_aliases_norm):
            score = 5
        elif query_norm == name_norm:
            score = 1
        elif query_norm in name_norm:
            score = 10 + len(name_norm)
        elif terms and all(term in name_norm for term in terms):
            score = 20 + len(name_norm)

        if score is not None:
            scored.append((score, stop))

    scored.sort(key=lambda item: item[0])
    return [stop for _score, stop in scored[:limit]]


def _build_catalog_id_index(catalog):
    out = {}
    for stop in catalog:
        for alias in stop.get("id_aliases_norm", [stop.get("id_norm")]):
            if alias and alias not in out:
                out[alias] = stop
    return out


async def _get_catalog_stops(hass, force_refresh=False):
    now = time.monotonic()
    cached = _CATALOG_CACHE.get("data") or []
    expires_at = float(_CATALOG_CACHE.get("expires_at") or 0.0)

    if not force_refresh and cached and now < expires_at:
        return cached

    try:
        api = VigoBusApi(async_get_clientsession(hass))
        data = await api.get_paradas()
        stops = api._extract_stops(data)
        catalog = [item for item in (_extract_catalog_stop(stop) for stop in stops) if item]

        _CATALOG_CACHE["data"] = catalog
        _CATALOG_CACHE["expires_at"] = now + CATALOG_CACHE_TTL_SECONDS
        return catalog
    except Exception:
        # Fallback to stale cache when online refresh fails.
        return cached
