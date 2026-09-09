import asyncio

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VigoBusApi
from .const import (
    DEFAULT_DEVICE_NEAREST_MAX_CANDIDATES,
    DEFAULT_DEVICE_NEAREST_TIE_MARGIN_M,
    DOMAIN,
    MAX_DEVICE_NEAREST_MAX_CANDIDATES,
    MAX_DEVICE_NEAREST_TIE_MARGIN_M,
    MIN_DEVICE_NEAREST_MAX_CANDIDATES,
    MIN_DEVICE_NEAREST_TIE_MARGIN_M,
    SERVICE_NEAREST_STOPS,
    SERVICE_REFRESH,
)
from .coordinator import VigoBusCoordinator

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


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
                hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
            if hass.services.has_service(DOMAIN, SERVICE_NEAREST_STOPS):
                hass.services.async_remove(DOMAIN, SERVICE_NEAREST_STOPS)
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
