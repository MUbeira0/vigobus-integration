"""Calendar of the VigoBus line alerts: what is in force and what is coming.

Each distinct alert is an all-day event from its start to its end date, so the
alerts show up in Home Assistant's calendar view and can drive calendar
triggers ("an alert starts") without reading attributes.
"""

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .logic import alert_event_span, collect_alerts


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VigoBusAlertsCalendar(coordinator, entry.entry_id)])


class VigoBusAlertsCalendar(CoordinatorEntity, CalendarEntity):
    _attr_icon = "mdi:bus-alert"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator)
        self._attr_name = "VigoBus calendario de avisos"
        self._attr_unique_id = f"vigobus_{entry_id}_calendario_avisos"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_servicio")},
            name="VigoBus servicio",
            manufacturer="VigoBus",
            model="Servicio",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _events(self, today=None):
        today = today or dt_util.now().date()
        events = []
        for alert in collect_alerts(self.coordinator.data):
            span = alert_event_span(alert, today)
            if span is None:
                continue
            start, end = span
            lines = str(alert.get("lineas") or "").strip()
            stops = ", ".join(alert.get("stops") or [])
            parts = [str(alert.get("description") or "").strip()]
            if lines:
                parts.append(f"Líneas: {lines}")
            if stops:
                parts.append(f"Paradas: {stops}")
            events.append(
                CalendarEvent(
                    start=start,
                    end=end,
                    summary=str(alert.get("title") or "Aviso de transporte"),
                    description="\n\n".join(part for part in parts if part) or None,
                    uid=str(alert.get("id_publicacion") or "") or None,
                )
            )
        return events

    @property
    def event(self):
        """The alert in force that ends first, or else the next one to start."""
        today = dt_util.now().date()
        events = self._events(today)
        current = [e for e in events if e.start <= today < e.end]
        if current:
            return min(current, key=lambda e: e.end)
        upcoming = [e for e in events if e.start > today]
        return min(upcoming, key=lambda e: e.start) if upcoming else None

    async def async_get_events(self, hass, start_date, end_date):
        first = start_date.date()
        last = end_date.date()
        return [e for e in self._events() if e.start < last and e.end > first]
