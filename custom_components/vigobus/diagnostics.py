"""Diagnostics support for VigoBus Pro.

Lets a user download a redacted snapshot of coordinator/config state from
Settings > Devices & Services > VigoBus Pro > Download diagnostics, instead
of having to paste logs by hand when reporting an issue.
"""

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import gtfs
from .const import DOMAIN

# Coordinates and custom names can identify where someone lives; entity ids
# (e.g. person.miguel) are left as-is since they're usually needed to debug
# which device/person a stop belongs to.
TO_REDACT = {
    "latitude",
    "longitude",
    "home_lat",
    "home_lon",
    "nearest_lat",
    "nearest_lon",
    "nearest_name",
    "name",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    stops = {}
    for key, value in (getattr(coordinator, "data", None) or {}).items():
        if not isinstance(value, dict):
            continue
        estimaciones = (value.get("data") or {}).get("estimaciones")
        stops[key] = {
            "stale": value.get("stale"),
            "stale_reason": value.get("stale_reason"),
            "updated_at": value.get("updated_at"),
            "last_success_at": value.get("last_success_at"),
            "last_error_at": value.get("last_error_at"),
            "consecutive_failures": value.get("consecutive_failures"),
            "alerts_count": value.get("alerts_count"),
            "bus_count": len(estimaciones) if isinstance(estimaciones, list) else 0,
        }

    update_interval = getattr(coordinator, "update_interval", None)

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "coordinator": {
            "last_success_at": getattr(coordinator, "_last_success_at", None),
            "last_error_at": getattr(coordinator, "_last_error_at", None),
            "consecutive_failures": getattr(coordinator, "_consecutive_failures", None),
            "update_interval_seconds": update_interval.total_seconds() if update_interval else None,
            "stops": stops,
        },
        # The trip planner's GTFS feed is public open data (no redaction
        # needed) and shared across every config entry, not per-entry state
        # — reported here anyway since this is the one diagnostics surface
        # users already know to reach for when something looks wrong.
        "gtfs": gtfs.cache_status(),
    }
