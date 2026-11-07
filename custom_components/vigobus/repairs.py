"""Repairs: offer to remove a configured stop that no longer exists."""

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant


class StopMissingRepairFlow(RepairsFlow):
    """Confirm, then drop the missing stop from the integration options."""

    def __init__(self, entry_id, stop_id):
        self._entry_id = entry_id
        self._stop_id = stop_id

    async def async_step_init(self, user_input=None):
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="confirm", data_schema=None)

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is not None:
            current = entry.options if "extra_stops" in entry.options else entry.data
            remaining = [
                stop
                for stop in (current.get("extra_stops") or [])
                if str(stop.get("id", "")).strip() != self._stop_id
            ]
            options = {**entry.options, "extra_stops": remaining}
            self.hass.config_entries.async_update_entry(entry, options=options)

        return self.async_create_entry(title="", data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict | None,
) -> data_entry_flow.FlowHandler:
    data = data or {}
    return StopMissingRepairFlow(str(data.get("entry_id", "")), str(data.get("stop_id", "")))
