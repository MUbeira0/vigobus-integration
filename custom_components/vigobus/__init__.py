import asyncio

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, SERVICE_REFRESH
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
        if not hass.data.get(DOMAIN) and hass.services.has_service(DOMAIN, SERVICE_REFRESH):
            hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
