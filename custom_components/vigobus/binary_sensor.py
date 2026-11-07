"""Binary sensors for automations: "bus arriving" and "leave now"."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_ARRIVING_THRESHOLD_MIN, DOMAIN
from .logic import estimaciones_for


def _is_nearest_key(key):
    return key == "nearest" or str(key).startswith("nearest_")


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]

    def entry_value(key, default=None):
        if key in entry.options:
            return entry.options.get(key)
        return entry.data.get(key, default)

    line_filters = {}
    keys = set()
    if entry_value("auto_nearest", True):
        keys.add("nearest")
        line_filters["nearest"] = str(entry_value("nearest_line_filter", "") or "").strip()
    for stop in entry_value("extra_stops", []) or []:
        name = stop.get("name")
        if name:
            keys.add(name)
            line_filters[name] = str(stop.get("line", "") or "").strip()
    keys.update(coordinator.data or {})

    entities = []
    for key in sorted(keys):
        data = (coordinator.data or {}).get(key, {}) or {}
        label = str(data.get("display_name") or "").strip() or key
        line_filter = line_filters.get(key, "")
        entities.append(
            VigoBusArrivingBinarySensor(coordinator, key, entry.entry_id, label, line_filter)
        )
        if _is_nearest_key(key):
            entities.append(
                VigoBusLeaveNowBinarySensor(coordinator, key, entry.entry_id, label, line_filter)
            )

    async_add_entities(entities)


class _VigoBusBinaryBase(CoordinatorEntity, BinarySensorEntity):
    _suffix = ""

    def __init__(self, coordinator, stop_key, entry_id, display_name, line_filter):
        super().__init__(coordinator)
        self.stop_key = stop_key
        self._entry_id = entry_id
        self._display_name = display_name
        self._line_filter = str(line_filter or "").strip()
        key_id = str(stop_key).lower().replace(" ", "_")

        self._attr_unique_id = f"vigobus_{entry_id}_{key_id}_{self._suffix}"
        # Same device as the stop's four sensors, so everything about a stop
        # is grouped together in Settings > Devices.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{key_id}")},
            name=f"VigoBus {display_name}",
            manufacturer="VigoBus",
            model="Parada por dispositivo"
            if stop_key != "nearest" and str(stop_key).startswith("nearest_")
            else "Parada",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _result(self):
        return (self.coordinator.data or {}).get(self.stop_key, {}) or {}

    @property
    def available(self):
        data = self._result()
        return bool(data.get("data") or data.get("stop"))


class VigoBusArrivingBinarySensor(_VigoBusBinaryBase):
    """On while the next bus is at most N minutes away."""

    _suffix = "llegando"

    def __init__(self, coordinator, stop_key, entry_id, display_name, line_filter):
        super().__init__(coordinator, stop_key, entry_id, display_name, line_filter)
        self._attr_name = f"VigoBus {display_name} llegando"
        self._attr_icon = "mdi:bus-alert"

    def _threshold(self):
        value = (
            self.coordinator.entry.options.get("arriving_threshold_min")
            if "arriving_threshold_min" in self.coordinator.entry.options
            else self.coordinator.entry.data.get(
                "arriving_threshold_min", DEFAULT_ARRIVING_THRESHOLD_MIN
            )
        )
        try:
            return int(value)
        except (TypeError, ValueError):
            return DEFAULT_ARRIVING_THRESHOLD_MIN

    @property
    def is_on(self):
        buses = estimaciones_for(self._result(), self._line_filter)
        if not buses:
            return False
        return buses[0]["minutos"] <= self._threshold()

    @property
    def extra_state_attributes(self):
        buses = estimaciones_for(self._result(), self._line_filter)
        attrs = {"threshold_min": self._threshold(), "stop_key": self.stop_key}
        if buses:
            attrs["minutes"] = buses[0]["minutos"]
            attrs["line"] = buses[0]["linea"]
            attrs["route"] = buses[0]["ruta"]
        return attrs


class VigoBusLeaveNowBinarySensor(_VigoBusBinaryBase):
    """On when you should leave now to catch the next bus you can still reach."""

    _suffix = "salir_ya"

    def __init__(self, coordinator, stop_key, entry_id, display_name, line_filter):
        super().__init__(coordinator, stop_key, entry_id, display_name, line_filter)
        self._attr_name = f"VigoBus {display_name} salir ya"
        self._attr_icon = "mdi:run-fast"

    @property
    def available(self):
        return super().available and self.coordinator.leave_info(self.stop_key, self._line_filter) is not None

    @property
    def is_on(self):
        info = self.coordinator.leave_info(self.stop_key, self._line_filter)
        if not info or info["leave_in"] is None:
            return False
        return info["leave_in"] <= 0

    @property
    def extra_state_attributes(self):
        info = self.coordinator.leave_info(self.stop_key, self._line_filter)
        if not info:
            return {}
        attrs = {
            "walk_min": info["walk_min"],
            "buffer_min": info["buffer_min"],
            "distance_m": info["distance_m"],
            "leave_in": info["leave_in"],
        }
        if info["bus"]:
            attrs["line"] = info["bus"]["linea"]
            attrs["bus_minutes"] = info["bus"]["minutos"]
        return attrs
