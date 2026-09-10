import asyncio
import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from . import gtfs, trip_planner
from .api import VigoBusApi
from .const import (
    DEFAULT_ALERTS_LANG,
    DEFAULT_DEVICE_NEAREST_MAX_CANDIDATES,
    DEFAULT_DEVICE_NEAREST_TIE_MARGIN_M,
    DEFAULT_STOP_SEARCH_LIMIT,
    DEFAULT_TRIP_MAX_ITINERARIES,
    DEFAULT_TRIP_MAX_TRANSFERS,
    DEFAULT_TRIP_MAX_WALK_M,
    DOMAIN,
    LIVE_CHECK_HORIZON_SECONDS,
    MAX_DEVICE_NEAREST_MAX_CANDIDATES,
    MAX_DEVICE_NEAREST_TIE_MARGIN_M,
    MAX_STOP_SEARCH_LIMIT,
    MAX_TRIP_MAX_ITINERARIES,
    MAX_TRIP_MAX_TRANSFERS,
    MAX_TRIP_MAX_WALK_M,
    MIN_DEVICE_NEAREST_MAX_CANDIDATES,
    MIN_DEVICE_NEAREST_TIE_MARGIN_M,
    MIN_STOP_SEARCH_LIMIT,
    MIN_TRIP_MAX_ITINERARIES,
    MIN_TRIP_MAX_TRANSFERS,
    MIN_TRIP_MAX_WALK_M,
    SERVICE_NEAREST_STOPS,
    SERVICE_PLAN_TRIP,
    SERVICE_REFRESH,
    SERVICE_SEARCH_STOPS,
)
from .coordinator import VigoBusCoordinator
from .stop_catalog import _get_catalog_stops, search_stops_ranked

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    coordinator = VigoBusCoordinator(hass, entry)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        async def _handle_refresh(call):
            target_entry_id = call.data.get("entry_id")
            coordinators = hass.data.get(DOMAIN, {})
            tasks = []

            if target_entry_id:
                coordinator_target = coordinators.get(target_entry_id)
                if coordinator_target:
                    tasks.append(coordinator_target.async_request_refresh())
            else:
                tasks.extend(item.async_request_refresh() for item in coordinators.values())

            if tasks:
                await asyncio.gather(*tasks)

        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH,
            _handle_refresh,
            schema=vol.Schema({vol.Optional("entry_id"): str}),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_NEAREST_STOPS):
        async def _handle_nearest_stops(call):
            api = VigoBusApi(async_get_clientsession(hass))
            candidates = await api.get_nearest_stops_with_eta(
                call.data["latitude"],
                call.data["longitude"],
                margin_m=call.data.get("tie_margin_m", DEFAULT_DEVICE_NEAREST_TIE_MARGIN_M),
                max_candidates=call.data.get(
                    "max_candidates", DEFAULT_DEVICE_NEAREST_MAX_CANDIDATES
                ),
                line=call.data.get("line") or None,
                lang=call.data.get("lang") or DEFAULT_ALERTS_LANG,
            )
            return {"candidates": candidates}

        hass.services.async_register(
            DOMAIN,
            SERVICE_NEAREST_STOPS,
            _handle_nearest_stops,
            schema=vol.Schema(
                {
                    vol.Required("latitude"): vol.Coerce(float),
                    vol.Required("longitude"): vol.Coerce(float),
                    vol.Optional("tie_margin_m"): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_DEVICE_NEAREST_TIE_MARGIN_M,
                            max=MAX_DEVICE_NEAREST_TIE_MARGIN_M,
                        ),
                    ),
                    vol.Optional("max_candidates"): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_DEVICE_NEAREST_MAX_CANDIDATES,
                            max=MAX_DEVICE_NEAREST_MAX_CANDIDATES,
                        ),
                    ),
                    vol.Optional("line"): str,
                    vol.Optional("lang"): str,
                }
            ),
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SEARCH_STOPS):
        async def _handle_search_stops(call):
            return await search_stops_handler(hass, call.data)

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEARCH_STOPS,
            _handle_search_stops,
            schema=vol.Schema(
                {
                    vol.Required("query"): str,
                    vol.Optional("limit"): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_STOP_SEARCH_LIMIT, max=MAX_STOP_SEARCH_LIMIT),
                    ),
                }
            ),
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_PLAN_TRIP):
        async def _handle_plan_trip(call):
            return await plan_trip_handler(hass, call.data)

        hass.services.async_register(
            DOMAIN,
            SERVICE_PLAN_TRIP,
            _handle_plan_trip,
            schema=vol.Schema(
                {
                    vol.Optional("origin_latitude"): vol.Coerce(float),
                    vol.Optional("origin_longitude"): vol.Coerce(float),
                    vol.Optional("origin_stop_id"): str,
                    vol.Optional("destination_latitude"): vol.Coerce(float),
                    vol.Optional("destination_longitude"): vol.Coerce(float),
                    vol.Optional("destination_stop_id"): str,
                    vol.Optional("depart_at"): str,
                    vol.Optional("max_transfers"): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_TRIP_MAX_TRANSFERS, max=MAX_TRIP_MAX_TRANSFERS),
                    ),
                    vol.Optional("max_walk_m"): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_TRIP_MAX_WALK_M, max=MAX_TRIP_MAX_WALK_M),
                    ),
                    vol.Optional("max_itineraries"): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_TRIP_MAX_ITINERARIES, max=MAX_TRIP_MAX_ITINERARIES),
                    ),
                    vol.Optional("include_live"): bool,
                }
            ),
            supports_response=SupportsResponse.ONLY,
        )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    return True


def _resolve_depart(depart_at, now_local):
    """("HH:MM" or None) + a tz-aware "now" -> ("YYYYMMDD", seconds_since_midnight).

    v1 only supports a same-day "HH:MM" (or "now", the default) — no full
    ISO-8601 date parsing, matching the forward-only "depart at" scope.
    """
    date_str = now_local.strftime("%Y%m%d")
    now_seconds = now_local.hour * 3600 + now_local.minute * 60 + now_local.second

    if not depart_at:
        return date_str, now_seconds

    try:
        hh, mm = str(depart_at).strip().split(":")
        return date_str, int(hh) * 3600 + int(mm) * 60
    except (ValueError, AttributeError):
        return date_str, now_seconds


async def _attach_live_first_leg(api, itinerary, now_seconds):
    """Best-effort: annotate the itinerary's first bus leg with a live
    estimacion for its boarding stop, so the answer isn't purely a
    timetable guess for the leg the rider is about to act on immediately.
    Never raises — callers already wrap this in a try/except.
    """
    first_bus = next((leg for leg in itinerary.get("legs", []) if leg.get("mode") == "bus"), None)
    if not first_bus:
        return

    scheduled_depart = first_bus.get("depart_seconds")
    if scheduled_depart is not None and scheduled_depart - now_seconds > LIVE_CHECK_HORIZON_SECONDS:
        return

    from_stop_id = first_bus.get("from_stop", {}).get("stop_id")
    if not from_stop_id:
        return

    paradas = await api.get_paradas()
    stops = api._extract_stops(paradas)
    vitrasa_id = None
    for stop in stops:
        if str(stop.get("stop_id") or "").strip() == from_stop_id:
            vitrasa_id = stop.get("id")
            break
    if vitrasa_id is None:
        return

    estimacion = await api.get_estimacion(vitrasa_id)
    estimaciones = (estimacion or {}).get("estimaciones", [])
    if not isinstance(estimaciones, list):
        return

    target_line = api._normalize_line(first_bus.get("line"))
    for item in estimaciones:
        if not isinstance(item, dict):
            continue
        if api._normalize_line(item.get("linea")) != target_line:
            continue
        try:
            minutos = int(item.get("minutos"))
        except (TypeError, ValueError):
            continue
        metros = item.get("metros")
        first_bus["live"] = {
            "minutos": minutos,
            "metros": metros,
            "is_live": isinstance(metros, (int, float)) and metros >= 0,
        }
        return


async def search_stops_handler(hass, data):
    """Body of the search_stops service — a plain function of (hass, call.data)
    so it's directly unit-testable without going through async_setup_entry."""
    catalog = await _get_catalog_stops(hass)
    matches = search_stops_ranked(
        data["query"],
        catalog,
        limit=data.get("limit", DEFAULT_STOP_SEARCH_LIMIT),
    )
    return {
        "stops": [
            {
                "id": stop["id"],
                "stop_id": stop.get("stop_id"),
                "name": stop["name"],
                "latitude": stop.get("lat"),
                "longitude": stop.get("lon"),
            }
            for stop in matches
        ]
    }


async def plan_trip_handler(hass, data):
    """Body of the plan_trip service — a plain function of (hass, call.data)
    so it's directly unit-testable without going through async_setup_entry."""
    has_origin_coords = data.get("origin_latitude") is not None and data.get("origin_longitude") is not None
    if not data.get("origin_stop_id") and not has_origin_coords:
        raise ServiceValidationError("Provide origin_stop_id or both origin_latitude/origin_longitude")

    has_dest_coords = (
        data.get("destination_latitude") is not None and data.get("destination_longitude") is not None
    )
    if not data.get("destination_stop_id") and not has_dest_coords:
        raise ServiceValidationError(
            "Provide destination_stop_id or both destination_latitude/destination_longitude"
        )

    api = VigoBusApi(async_get_clientsession(hass))
    max_walk_m = data.get("max_walk_m", DEFAULT_TRIP_MAX_WALK_M)
    max_transfers = data.get("max_transfers", DEFAULT_TRIP_MAX_TRANSFERS)
    max_itineraries = data.get("max_itineraries", DEFAULT_TRIP_MAX_ITINERARIES)
    include_live = data.get("include_live", True)

    now_local = dt_util.now()
    now_seconds = now_local.hour * 3600 + now_local.minute * 60 + now_local.second
    date_str, depart_seconds = _resolve_depart(data.get("depart_at"), now_local)

    index = await gtfs.get_gtfs_index(async_get_clientsession(hass), logger=_LOGGER)
    if not gtfs.active_services(index, date_str):
        # The cached index might just be stale (this feed only ever
        # activates a service day via a calendar_dates.txt row on a rolling
        # horizon) — force one refresh before concluding there's really no
        # service, rather than answering wrong.
        index = await gtfs.get_gtfs_index(async_get_clientsession(hass), logger=_LOGGER, force=True)

    if data.get("origin_stop_id"):
        origin_access = [{"stop_id": data["origin_stop_id"], "walk_seconds": 0}]
    else:
        origin_access = await hass.async_add_executor_job(
            trip_planner.nearest_index_stops,
            index,
            data["origin_latitude"],
            data["origin_longitude"],
            max_walk_m,
        )

    if data.get("destination_stop_id"):
        dest_access = [{"stop_id": data["destination_stop_id"], "walk_seconds": 0}]
    else:
        dest_access = await hass.async_add_executor_job(
            trip_planner.nearest_index_stops,
            index,
            data["destination_latitude"],
            data["destination_longitude"],
            max_walk_m,
        )

    result = await hass.async_add_executor_job(
        trip_planner.plan,
        index,
        origin_access,
        dest_access,
        date_str,
        depart_seconds,
        max_transfers + 1,
        max_itineraries,
    )

    try:
        line_colors = await api.get_line_colors(logger=_LOGGER)
        trip_planner.attach_colors(result, line_colors)
    except Exception:
        _LOGGER.debug("VigoBus: unable to attach line colors to trip plan", exc_info=True)

    if include_live and result["itineraries"]:
        try:
            await _attach_live_first_leg(api, result["itineraries"][0], now_seconds)
        except Exception:
            _LOGGER.debug("VigoBus: unable to attach live data to trip plan", exc_info=True)

    result["service_date"] = date_str
    return result


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
                hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
            if hass.services.has_service(DOMAIN, SERVICE_NEAREST_STOPS):
                hass.services.async_remove(DOMAIN, SERVICE_NEAREST_STOPS)
            if hass.services.has_service(DOMAIN, SERVICE_SEARCH_STOPS):
                hass.services.async_remove(DOMAIN, SERVICE_SEARCH_STOPS)
            if hass.services.has_service(DOMAIN, SERVICE_PLAN_TRIP):
                hass.services.async_remove(DOMAIN, SERVICE_PLAN_TRIP)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(hass: HomeAssistant, entry: ConfigEntry, device_entry) -> bool:
    """Allow deleting a VigoBus device (stop) from Settings > Devices.

    Without this hook Home Assistant hides the "Delete" button entirely for
    any device tied to a live config entry. These devices are safe to delete
    on request: a stop that's still configured (home nearest, an extra stop,
    a tracked person/device) is recreated automatically the next time the
    entry is set up (its unique_id is stable), while one the user removed
    from the config stays gone for good — either way there's nothing to
    reconcile here.
    """
    return True
