from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import split_line_variant
from .const import DOMAIN
from .logic import collect_alerts, compute_leave  # noqa: F401  (compute_leave re-exported for tests)


def _normalize_line(value):
    return str(value or "").strip().upper().replace(" ", "")


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
    nearest_line_filter = str(entry_value("nearest_line_filter", "") or "").strip()

    entities = []
    keys = set()
    line_filters = {}

    if entry_value("auto_nearest", True):
        keys.add("nearest")
        line_filters["nearest"] = nearest_line_filter

    for stop in entry_value("extra_stops", []):
        name = stop.get("name")
        if name:
            keys.add(name)
            line_filters[name] = str(stop.get("line", "") or "").strip()

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

    def _label_for(key):
        if key == "nearest":
            return nearest_label
        data = (coordinator.data or {}).get(key, {}) or {}
        display = str(data.get("display_name") or "").strip()
        return display or key

    for key in sorted(keys):
        label = _label_for(key)
        line_filter = line_filters.get(key, "")
        add_entity(
            VigoBusSensor(
                coordinator, key, entry_id=entry_id, display_name=label, line_filter=line_filter
            )
        )
        add_entity(
            VigoBusLineSensor(
                coordinator, key, entry_id=entry_id, display_name=label, line_filter=line_filter
            )
        )
        add_entity(
            VigoBusRouteSensor(
                coordinator, key, entry_id=entry_id, display_name=label, line_filter=line_filter
            )
        )
        add_entity(
            VigoBusUpcomingSensor(
                coordinator, key, entry_id=entry_id, display_name=label, line_filter=line_filter
            )
        )
        add_entity(
            VigoBusReliabilitySensor(
                coordinator, key, entry_id=entry_id, display_name=label, line_filter=line_filter
            )
        )
        if key == "nearest" or str(key).startswith("nearest_"):
            add_entity(
                VigoBusLeaveInSensor(
                    coordinator, key, entry_id=entry_id, display_name=label, line_filter=line_filter
                )
            )

    add_entity(VigoBusStatusSensor(coordinator, entry_id))
    for commute in entry_value("commutes", []) or []:
        name = str(commute.get("name") or "").strip()
        if name:
            add_entity(VigoBusCommuteSensor(coordinator, entry_id, name))

    async_add_entities(entities)



class VigoBusSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, stop_key, entry_id=None, display_name=None, line_filter=None):
        super().__init__(coordinator)

        self.stop_key = stop_key
        key_id = str(stop_key).lower().replace(" ", "_")
        self._entry_id = entry_id or "default"
        self._display_name = display_name or stop_key
        self._line_filter = str(line_filter or "").strip()

        self._attr_name = f"VigoBus {self._display_name}"
        self._attr_unique_id = f"vigobus_{self._entry_id}_{key_id}"
        self._attr_icon = "mdi:bus-clock"
        self._attr_native_unit_of_measurement = "min"

        is_device_nearest = stop_key != "nearest" and str(stop_key).startswith("nearest_")
        model = "Parada por dispositivo" if is_device_nearest else "Parada"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{key_id}")},
            name=self._attr_name,
            manufacturer="VigoBus",
            model=model,
            entry_type=DeviceEntryType.SERVICE,
        )

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
                    from math import atan2, cos, radians, sin, sqrt
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

            line_filter = _normalize_line(self._line_filter)

            valid = []
            for bus in estimaciones:
                if not isinstance(bus, dict):
                    continue
                minutos = bus.get("minutos")
                try:
                    minutos = int(minutos)
                except (TypeError, ValueError):
                    continue

                eff_line, eff_route = split_line_variant(bus.get("linea"), bus.get("ruta"))
                base_norm = _normalize_line(bus.get("linea"))
                eff_norm = _normalize_line(eff_line)
                if line_filter and line_filter not in (base_norm, eff_norm):
                    continue

                line_colors = getattr(self.coordinator, "_line_colors", {}) or {}
                valid.append(
                    {
                        "linea": eff_line,
                        "ruta": eff_route,
                        "metros": bus.get("metros"),
                        "minutos": minutos,
                        "color": line_colors.get(eff_norm) or line_colors.get(base_norm),
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
        attrs["line_filter"] = self._line_filter or None
        # Explicit flag so consumers (the companion card) can reliably tell a
        # per-device/person nearest sensor apart from the home "nearest" one
        # or a manually configured extra stop, without having to infer it
        # from the entity_id — which is derived from the (localized) name
        # and isn't a stable signal across languages.
        attrs["is_device_nearest"] = self.stop_key != "nearest" and self.stop_key.startswith("nearest_")
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


class _VigoBusDerivedSensor(VigoBusSensor):
    """Line / route / upcoming sensors of a stop.

    They share the stop's coordinator entry with the main sensor, so repeating
    the full bus list and alert list on each of them just stores the same
    payload several times in the recorder. They keep the identifying and
    health attributes; the full detail lives on the main stop sensor.
    """

    @property
    def extra_state_attributes(self):
        entry_data = self._entry_data()
        return {
            "stop_key": self.stop_key,
            "stop_name": entry_data.get("stop_name") or self._display_name,
            "line_filter": self._line_filter or None,
            "updated_at": entry_data.get("updated_at"),
            "alerts_count": entry_data.get("alerts_count", 0),
            "stale": bool(entry_data.get("stale", False)),
            "last_success_at": entry_data.get("last_success_at"),
        }


class VigoBusLineSensor(_VigoBusDerivedSensor):
    def __init__(self, coordinator, stop_key, entry_id=None, display_name=None, line_filter=None):
        super().__init__(
            coordinator, stop_key, entry_id=entry_id, display_name=display_name, line_filter=line_filter
        )
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


class VigoBusRouteSensor(_VigoBusDerivedSensor):
    def __init__(self, coordinator, stop_key, entry_id=None, display_name=None, line_filter=None):
        super().__init__(
            coordinator, stop_key, entry_id=entry_id, display_name=display_name, line_filter=line_filter
        )
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


class VigoBusUpcomingSensor(_VigoBusDerivedSensor):
    def __init__(self, coordinator, stop_key, entry_id=None, display_name=None, line_filter=None):
        super().__init__(
            coordinator, stop_key, entry_id=entry_id, display_name=display_name, line_filter=line_filter
        )
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


class VigoBusLeaveInSensor(VigoBusSensor):
    """Minutes until you should leave home to catch a bus you can still reach.

    Uses the straight-line distance to the stop (with a detour factor) and your
    walking speed, plus a safety buffer set in Configure. 0 means leave now.
    """

    def __init__(self, coordinator, stop_key, entry_id=None, display_name=None, line_filter=None):
        super().__init__(
            coordinator, stop_key, entry_id=entry_id, display_name=display_name, line_filter=line_filter
        )
        key_id = str(stop_key).lower().replace(" ", "_")
        self._attr_name = f"VigoBus {self._display_name} salir en"
        self._attr_unique_id = f"vigobus_{self._entry_id}_{key_id}_salir_en"
        self._attr_icon = "mdi:run"
        self._attr_native_unit_of_measurement = "min"

    def _info(self):
        return self.coordinator.leave_info(self.stop_key, self._line_filter)

    @property
    def available(self):
        return super().available and self._info() is not None

    @property
    def state(self):
        info = self._info()
        return None if not info else info["leave_in"]

    @property
    def extra_state_attributes(self):
        info = self._info()
        if not info:
            return {"stop_key": self.stop_key}
        attrs = {
            "stop_key": self.stop_key,
            "walk_min": info["walk_min"],
            "buffer_min": info["buffer_min"],
            "distance_m": info["distance_m"],
        }
        if info["bus"]:
            attrs["line"] = info["bus"]["linea"]
            attrs["bus_minutes"] = info["bus"]["minutos"]
        if info["missed"]:
            attrs["missed_line"] = info["missed"]["linea"]
            attrs["missed_minutes"] = info["missed"]["minutos"]
        return attrs


class VigoBusReliabilitySensor(VigoBusSensor):
    """Share of the stop's listed buses that had a live GPS position over the
    last scans. A low value means most estimates are timetable guesses."""

    def __init__(self, coordinator, stop_key, entry_id=None, display_name=None, line_filter=None):
        super().__init__(
            coordinator, stop_key, entry_id=entry_id, display_name=display_name, line_filter=line_filter
        )
        key_id = str(stop_key).lower().replace(" ", "_")
        self._attr_name = f"VigoBus {self._display_name} fiabilidad en vivo"
        self._attr_unique_id = f"vigobus_{self._entry_id}_{key_id}_fiabilidad"
        self._attr_icon = "mdi:crosshairs-gps"
        self._attr_native_unit_of_measurement = "%"
        self._attr_entity_registry_enabled_default = False

    @property
    def available(self):
        return True

    @property
    def state(self):
        return self.coordinator.reliability_pct(self.stop_key)

    @property
    def extra_state_attributes(self):
        return {"stop_key": self.stop_key}


class VigoBusStatusSensor(CoordinatorEntity, SensorEntity):
    """Health of the data feed: ok, alerts, degraded or offline."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["ok", "alerts", "degraded", "offline"]
    _attr_icon = "mdi:bus-multiple"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator)
        self._attr_name = "VigoBus estado del servicio"
        self._attr_unique_id = f"vigobus_{entry_id}_estado_servicio"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_servicio")},
            name="VigoBus servicio",
            manufacturer="VigoBus",
            model="Servicio",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self):
        return self.coordinator.service_status

    @property
    def extra_state_attributes(self):
        coordinator = self.coordinator
        # The same alert is attached to every stop served by an affected line,
        # so it is counted once here, not once per stop.
        alerts = collect_alerts(coordinator.data)
        return {
            "consecutive_failures": coordinator._consecutive_failures,
            "last_success_at": coordinator._last_success_at,
            "last_error_at": coordinator._last_error_at,
            "active_alerts": sum(1 for alert in alerts if alert.get("status") == "active"),
            "upcoming_alerts": sum(1 for alert in alerts if alert.get("status") == "upcoming"),
            "alerts": alerts,
        }


class VigoBusCommuteSensor(CoordinatorEntity, SensorEntity):
    """The best bus option for a commute, planned shortly before you usually
    leave. The state is the departure time; the attributes carry the summary."""

    _attr_icon = "mdi:briefcase-clock"

    def __init__(self, coordinator, entry_id, name):
        super().__init__(coordinator)
        self._commute_name = name
        slug = "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_")
        self._attr_name = f"VigoBus trayecto {name}"
        self._attr_unique_id = f"vigobus_{entry_id}_trayecto_{slug}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_servicio")},
            name="VigoBus servicio",
            manufacturer="VigoBus",
            model="Servicio",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _result(self):
        return (self.coordinator.commute_results or {}).get(self._commute_name) or {}

    @property
    def native_value(self):
        return self._result().get("depart")

    @property
    def extra_state_attributes(self):
        result = self._result()
        return {"commute": self._commute_name, **result}
