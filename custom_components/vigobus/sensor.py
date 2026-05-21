from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


def _unique_text_items(*values):
    items = []
    seen = set()

    for value in values:
        text = str(value or "").strip()
        if not text or text == "-":
            continue

        key = text.upper()
        if key in seen:
            continue

        seen.add(key)
        items.append(text)

    return items


def _get_default_nearest_label(hass):
    language = str(getattr(getattr(hass, "config", None), "language", "") or "").lower()

    if language.startswith("es"):
        return "Cercana"

    if language.startswith("en"):
        return "Nearest"

    if language.startswith("gl"):
        return "M\u00e1is pr\u00f3xima"

    return "Cercana"


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]

    def entry_value(key, default=None):
        if key in entry.options:
            return entry.options.get(key)
        return entry.data.get(key, default)

    nearest_name = str(entry_value("nearest_name", "") or "").strip()
    nearest_label = nearest_name or _get_default_nearest_label(hass)

    entities = []
    keys = set()

    if entry_value("auto_nearest", True):
        keys.add("nearest")

    for stop in entry_value("extra_stops", []):
        name = stop.get("name")
        if name:
            keys.add(name)

    for key in (coordinator.data or {}):
        keys.add(key)

    # Avoid duplicates by tracking unique_ids
    unique_ids = set()
    entry_id = entry.entry_id

    def add_entity(entity):
        if entity.unique_id in unique_ids:
            return
        unique_ids.add(entity.unique_id)
        entities.append(entity)

    for key in sorted(keys):
        label = nearest_label if key == "nearest" else key
        add_entity(VigoBusSensor(coordinator, key, entry_id=entry_id, display_name=label))
        add_entity(VigoBusLineSensor(coordinator, key, entry_id=entry_id, display_name=label))
        add_entity(VigoBusRouteSensor(coordinator, key, entry_id=entry_id, display_name=label))
        add_entity(VigoBusUpcomingSensor(coordinator, key, entry_id=entry_id, display_name=label))

    async_add_entities(entities)



class VigoBusSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, stop_key, entry_id=None, display_name=None):
        super().__init__(coordinator)

        self.stop_key = stop_key
        key_id = str(stop_key).lower().replace(" ", "_")
        self._entry_id = entry_id or "default"
        self._display_name = display_name or stop_key

        self._attr_name = f"VigoBus {self._display_name}"
        self._attr_unique_id = f"vigobus_{self._entry_id}_{key_id}"
        self._attr_icon = "mdi:bus-clock"
        self._attr_native_unit_of_measurement = "min"

    def _entry_data(self):
        return self.coordinator.data.get(self.stop_key, {}) if self.coordinator.data else {}

    @property
    def available(self):
        data = self._entry_data()
        return bool(data.get("data") or data.get("stop"))

    def _get_debug_info(self):
        # Solo para nearest
        if self.stop_key != "nearest":
            return {}
        try:
            coordinator = self.coordinator
            debug = {}
            # Coordenadas home
            home = coordinator.hass.states.get("zone.home")
            if home:
                debug["home_lat"] = home.attributes.get("latitude")
                debug["home_lon"] = home.attributes.get("longitude")
            else:
                debug["home_lat"] = None
                debug["home_lon"] = None
            # Última parada calculada
            stop = getattr(coordinator, "closest_stop", None)
            if stop:
                debug["nearest_id"] = stop.get("id")
                debug["nearest_stop_id"] = stop.get("stop_id")
                debug["nearest_lat"] = stop.get("latitud")
                debug["nearest_lon"] = stop.get("longitud")
                # Distancia
                try:
                    lat1 = float(debug["home_lat"])
                    lon1 = float(debug["home_lon"])
                    lat2 = float(debug["nearest_lat"])
                    lon2 = float(debug["nearest_lon"])
                    from math import radians, sin, cos, sqrt, atan2
                    R = 6371000
                    phi1 = radians(lat1)
                    phi2 = radians(lat2)
                    dphi = radians(lat2 - lat1)
                    dlambda = radians(lon2 - lon1)
                    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
                    debug["nearest_dist_m"] = 2 * R * atan2(sqrt(a), sqrt(1 - a))
                except Exception:
                    debug["nearest_dist_m"] = None
            else:
                debug["nearest_stop_id"] = None
                debug["nearest_lat"] = None
                debug["nearest_lon"] = None
                debug["nearest_dist_m"] = None
            # Cuántas paradas hay en el último fetch
            stops = []
            try:
                api = getattr(coordinator, "api", None)
                if api:
                    data = coordinator.data.get("nearest", {}).get("stop", {})
                    stops = getattr(api, "_extract_stops", lambda x: [])(data)
            except Exception:
                pass
            debug["stops_count"] = len(stops)
            return debug
        except Exception:
            return {"debug_error": True}

    def _get_estimaciones(self):
        try:
            data = self._entry_data().get("data", {})
            estimaciones = data.get("estimaciones", [])
            if not isinstance(estimaciones, list):
                return []

            valid = []
            for bus in estimaciones:
                if not isinstance(bus, dict):
                    continue
                minutos = bus.get("minutos")
                try:
                    minutos = int(minutos)
                except (TypeError, ValueError):
                    continue

                valid.append(
                    {
                        "linea": bus.get("linea"),
                        "ruta": bus.get("ruta"),
                        "metros": bus.get("metros"),
                        "minutos": minutos,
                    }
                )

            valid.sort(key=lambda item: item["minutos"])
            return valid
        except Exception:
            return []

    @property
    def state(self):
        estimaciones = self._get_estimaciones()
        if not estimaciones:
            return None

        return estimaciones[0]["minutos"]

    @property
    def extra_state_attributes(self):
        estimaciones = self._get_estimaciones()
        attrs = {}
        entry_data = self._entry_data()
        if estimaciones:
            first = estimaciones[0]
            rutas = _unique_text_items(
                *(bus.get("ruta") for bus in estimaciones),
                first.get("ruta"),
            )
            attrs = {
                "linea": first.get("linea"),
                "ruta": first.get("ruta"),
                "rutas": rutas,
                "metros": first.get("metros"),
                "proximo_minutos": first.get("minutos"),
                "buses": estimaciones,
                "total_buses": len(estimaciones),
            }

        attrs["stop_key"] = self.stop_key
        attrs["stop_name"] = entry_data.get("stop_name") or self._display_name
        attrs["updated_at"] = entry_data.get("updated_at")
        attrs["lines"] = entry_data.get("lines", [])
        attrs["alerts"] = entry_data.get("alerts", [])
        attrs["alerts_count"] = entry_data.get("alerts_count", 0)
        attrs["stale"] = bool(entry_data.get("stale", False))
        attrs["stale_reason"] = entry_data.get("stale_reason")
        attrs["stale_at"] = entry_data.get("stale_at")
        attrs["last_success_at"] = entry_data.get("last_success_at")
        attrs["last_error_at"] = entry_data.get("last_error_at")
        attrs["consecutive_failures"] = entry_data.get("consecutive_failures")
        # Añadir debug si es nearest
        attrs.update(self._get_debug_info())
        return attrs


class VigoBusLineSensor(VigoBusSensor):
    def __init__(self, coordinator, stop_key, entry_id=None, display_name=None):
        super().__init__(coordinator, stop_key, entry_id=entry_id, display_name=display_name)
        key_id = str(stop_key).lower().replace(" ", "_")
        self._attr_name = f"VigoBus {self._display_name} linea"
        self._attr_unique_id = f"vigobus_{self._entry_id}_{key_id}_linea"
        self._attr_icon = "mdi:bus"
        self._attr_native_unit_of_measurement = None

    @property
    def state(self):
        estimaciones = self._get_estimaciones()
        if not estimaciones:
            return None

        return estimaciones[0].get("linea")


class VigoBusRouteSensor(VigoBusSensor):
    def __init__(self, coordinator, stop_key, entry_id=None, display_name=None):
        super().__init__(coordinator, stop_key, entry_id=entry_id, display_name=display_name)
        key_id = str(stop_key).lower().replace(" ", "_")
        self._attr_name = f"VigoBus {self._display_name} ruta"
        self._attr_unique_id = f"vigobus_{self._entry_id}_{key_id}_ruta"
        self._attr_icon = "mdi:map-marker-path"
        self._attr_native_unit_of_measurement = None

    @property
    def state(self):
        estimaciones = self._get_estimaciones()
        if not estimaciones:
            return None

        return estimaciones[0].get("ruta")


class VigoBusUpcomingSensor(VigoBusSensor):
    def __init__(self, coordinator, stop_key, entry_id=None, display_name=None):
        super().__init__(coordinator, stop_key, entry_id=entry_id, display_name=display_name)
        key_id = str(stop_key).lower().replace(" ", "_")
        self._attr_name = f"VigoBus {self._display_name} proximos"
        self._attr_unique_id = f"vigobus_{self._entry_id}_{key_id}_proximos"
        self._attr_icon = "mdi:format-list-bulleted"
        self._attr_native_unit_of_measurement = None

    @property
    def state(self):
        estimaciones = self._get_estimaciones()
        if not estimaciones:
            return None

        items = []
        for bus in estimaciones[:3]:
            linea = bus.get("linea") or "-"
            minutos = bus.get("minutos")
            items.append(f"{linea} {minutos}m")

        return " | ".join(items)
