"""Event entity fired when a new line alert appears."""

from homeassistant.components.event import EventEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, SIGNAL_ALERT_LIFECYCLE, SIGNAL_NEW_ALERTS

EVENT_NEW_ALERT = "new_alert"
EVENT_ALERT_STARTED = "alert_started"
EVENT_ALERT_ENDED = "alert_ended"
BUS_EVENT_NEW_ALERT = "vigobus_new_alert"
BUS_EVENT_ALERT_STARTED = "vigobus_alert_started"
BUS_EVENT_ALERT_ENDED = "vigobus_alert_ended"


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([VigoBusAlertEvent(entry.entry_id)])


class VigoBusAlertEvent(EventEntity):
    """Fires ``new_alert`` once for every alert that was not there on the
    previous scan, ``alert_started`` when an upcoming alert comes into force and
    ``alert_ended`` when an alert is gone, so automations can react without
    polling attributes."""

    _attr_should_poll = False
    _attr_event_types = [EVENT_NEW_ALERT, EVENT_ALERT_STARTED, EVENT_ALERT_ENDED]
    _attr_icon = "mdi:bell-alert"

    def __init__(self, entry_id):
        self._entry_id = entry_id
        self._attr_name = "VigoBus avisos"
        self._attr_unique_id = f"vigobus_{entry_id}_avisos_evento"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_servicio")},
            name="VigoBus servicio",
            manufacturer="VigoBus",
            model="Servicio",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_NEW_ALERTS.format(self._entry_id), self._handle_new_alerts
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ALERT_LIFECYCLE.format(self._entry_id), self._handle_lifecycle
            )
        )

    @staticmethod
    def _payload(alert):
        return {
            "id": alert.get("id_publicacion"),
            "title": alert.get("title"),
            "lines": alert.get("lineas"),
            "start": alert.get("inicio"),
            "end": alert.get("fin"),
            "description": alert.get("description"),
            "kind": alert.get("kind"),
            "status": alert.get("status"),
        }

    @callback
    def _handle_lifecycle(self, items):
        bus_events = {EVENT_ALERT_STARTED: BUS_EVENT_ALERT_STARTED, EVENT_ALERT_ENDED: BUS_EVENT_ALERT_ENDED}
        for event_type, alert in items:
            payload = self._payload(alert)
            self._trigger_event(event_type, payload)
            self.hass.bus.async_fire(bus_events[event_type], {**payload, "entry_id": self._entry_id})
        self.async_write_ha_state()

    @callback
    def _handle_new_alerts(self, alerts):
        for alert in alerts:
            payload = {
                "id": alert.get("id_publicacion"),
                "title": alert.get("title"),
                "lines": alert.get("lineas"),
                "start": alert.get("inicio"),
                "end": alert.get("fin"),
                "description": alert.get("description"),
                "kind": alert.get("kind"),
                "status": alert.get("status"),
            }
            self._trigger_event(EVENT_NEW_ALERT, payload)
            # An event entity only keeps the last event it fired, so when
            # several alerts arrive in the same scan an automation watching
            # the entity would miss all but one. The bus event carries each.
            self.hass.bus.async_fire(BUS_EVENT_NEW_ALERT, {**payload, "entry_id": self._entry_id})
        self.async_write_ha_state()
