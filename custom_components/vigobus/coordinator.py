import logging
from datetime import timedelta

from aiohttp import ClientError

from homeassistant.components import persistent_notification
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
)

from .api import VigoBusApi
from .const import (
    DEFAULT_ALERTS_LANG,
    DEFAULT_ALERTS_MAX_PER_STOP,
    DEFAULT_AUTO_NEAREST_DEVICES,
    DEFAULT_NOTIFY_COOLDOWN_MIN,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_NOTIFY_MINUTES,
    DEFAULT_NEAREST_RECALC_DISTANCE_M,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


_LOGGER = logging.getLogger(__name__)


class VigoBusCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry

        self.session = async_get_clientsession(hass)

        self.api = VigoBusApi(self.session)

        # closest_stop keeps the home result for backward compatibility
        # (sensor debug info still reads it). Per-target caches below hold the
        # home entry plus one entry per tracked device/person.
        self.closest_stop = None
        self._closest_stops = {}
        self._nearest_anchor = {}
        self._line_colors = {}
        self._last_success_at = None
        self._last_error_at = None
        self._consecutive_failures = 0
        self._last_notification_at = {}
        self._nearest_recalc_distance_m = int(
            entry.options.get(
                "nearest_recalc_distance_m",
                entry.data.get("nearest_recalc_distance_m", DEFAULT_NEAREST_RECALC_DISTANCE_M),
            )
        )
        scan_interval = int(
            entry.options.get(
                "scan_interval",
                entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL),
            )
        )

        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    def _entry_value(self, key, default=None):
        if key in self.entry.options:
            return self.entry.options.get(key)
        return self.entry.data.get(key, default)

    def _should_refresh_nearest(self, key, lat, lon):
        if self._closest_stops.get(key) is None:
            return True

        anchor = self._nearest_anchor.get(key)
        if not anchor or anchor[0] is None or anchor[1] is None:
            return True

        moved_m = self.api.haversine(anchor[0], anchor[1], lat, lon)
        return moved_m >= self._nearest_recalc_distance_m

    def _home_coords(self):
        home = self.hass.states.get("zone.home")
        if home:
            lat = home.attributes.get("latitude")
            lon = home.attributes.get("longitude")
            if lat is not None and lon is not None:
                return lat, lon
        else:
            _LOGGER.warning("zone.home is not available yet, using HA config coordinates")

        return self.hass.config.latitude, self.hass.config.longitude

    def _discover_device_entities(self):
        """Return person/GPS device_tracker entity ids for auto creation."""
        ids = []
        for state in self.hass.states.async_all("person"):
            ids.append(state.entity_id)
        for state in self.hass.states.async_all("device_tracker"):
            if str(state.attributes.get("source_type") or "").lower() == "gps":
                ids.append(state.entity_id)
        return ids

    def _nearest_targets(self):
        """Build the list of nearest-stop targets to compute this cycle.

        Each target is (key, display_name, lat, lon). The home target keeps the
        legacy key ``"nearest"`` so it is never removed; device/person targets
        use ``nearest_<slug>`` keys and are purely additive.
        """
        targets = []

        # Home target (classic behaviour) — independent, never dropped.
        if self._entry_value("auto_nearest", True):
            lat, lon = self._home_coords()
            if lat is not None and lon is not None:
                name = str(self._entry_value("nearest_name", "") or "").strip()
                targets.append(("nearest", name, lat, lon))

        # Device/person targets: explicit selection + optional auto discovery.
        entity_ids = list(self._entry_value("nearest_devices", []) or [])
        if bool(self._entry_value("auto_nearest_devices", DEFAULT_AUTO_NEAREST_DEVICES)):
            entity_ids.extend(self._discover_device_entities())

        seen = set()
        for entity_id in entity_ids:
            entity_id = str(entity_id or "").strip()
            if not entity_id or entity_id in seen:
                continue
            seen.add(entity_id)

            state = self.hass.states.get(entity_id)
            if not state or state.state in ("unknown", "unavailable", "", None):
                continue

            lat = state.attributes.get("latitude")
            lon = state.attributes.get("longitude")
            if lat is None or lon is None:
                continue

            key = f"nearest_{slugify(entity_id)}"
            name = str(state.attributes.get("friendly_name") or entity_id).strip()
            targets.append((key, name, lat, lon))

        return targets

    async def _resolve_nearest_target(self, key, name, lat, lon, updated_at, alerts_index):
        """Resolve a single nearest target into a results entry (or None)."""
        if self._should_refresh_nearest(key, lat, lon):
            stop = await self.api.get_nearest_stop(lat, lon, logger=_LOGGER)
            if stop:
                self._closest_stops[key] = stop
                self._nearest_anchor[key] = (lat, lon)
                if key == "nearest":
                    self.closest_stop = stop

        stop = self._closest_stops.get(key)
        if not stop:
            _LOGGER.warning("No nearest stop could be resolved for %s", key)
            return None

        stop_id = self._extract_stop_id(stop)
        if stop_id is None:
            _LOGGER.warning("Nearest stop found for %s but no stop ID key was detected", key)
            return None

        entry = {
            "stop": stop,
            "stop_name": name,
            "display_name": name,
            "updated_at": updated_at,
            "data": await self.api.get_estimacion(stop_id),
        }
        self._attach_alerts(entry, alerts_index)
        return entry

    def _minutes_from_result(self, result):
        estimaciones = (result or {}).get("data", {}).get("estimaciones", [])
        if not isinstance(estimaciones, list):
            return None

        values = []
        for item in estimaciones:
            if not isinstance(item, dict):
                continue
            try:
                values.append(int(item.get("minutos")))
            except (TypeError, ValueError):
                continue

        if not values:
            return None
        return min(values)

    async def _maybe_send_notification(self, stop_key, result):
        if not bool(self._entry_value("notify_enabled", DEFAULT_NOTIFY_ENABLED)):
            return

        threshold = int(self._entry_value("notify_minutes", DEFAULT_NOTIFY_MINUTES))
        cooldown_min = int(self._entry_value("notify_cooldown_min", DEFAULT_NOTIFY_COOLDOWN_MIN))

        minutes = self._minutes_from_result(result)
        if minutes is None or minutes > threshold:
            return

        now = dt_util.utcnow()
        last_sent = self._last_notification_at.get(stop_key)
        if last_sent is not None:
            elapsed = (now - last_sent).total_seconds()
            if elapsed < cooldown_min * 60:
                return

        stop_name = (result or {}).get("stop_name") or stop_key
        title = "VigoBus aviso"
        message = f"{stop_name}: pr\u00f3ximo bus en {minutes} min (umbral {threshold} min)."
        notification_id = f"vigobus_alert_{self.entry.entry_id}_{stop_key}"
        persistent_notification.async_create(
            self.hass,
            message,
            title=title,
            notification_id=notification_id,
        )
        self._last_notification_at[stop_key] = now

    def _mark_results_stale(self, previous, reason):
        if not isinstance(previous, dict):
            return {}

        stale_at = dt_util.utcnow().isoformat()
        out = {}
        for key, value in previous.items():
            if not isinstance(value, dict):
                continue

            item = dict(value)
            item["stale"] = True
            item["stale_reason"] = reason
            item["stale_at"] = stale_at
            item["last_success_at"] = self._last_success_at
            item["last_error_at"] = self._last_error_at
            item["consecutive_failures"] = self._consecutive_failures
            out[key] = item

        return out

    def _extract_stop_id(self, stop):
        if not isinstance(stop, dict):
            return None

        properties = stop.get("properties")
        if not isinstance(properties, dict):
            properties = {}

        for key in ("id", "stop_id", "idparada", "parada"):
            value = stop.get(key)
            if value is not None:
                return str(value)
            prop_value = properties.get(key)
            if prop_value is not None:
                return str(prop_value)

        return None

    def _extract_lines_from_estimacion(self, data):
        estimaciones = (data or {}).get("estimaciones", [])
        if not isinstance(estimaciones, list):
            return []

        lines = set()
        for item in estimaciones:
            if not isinstance(item, dict):
                continue
            line = str(item.get("linea") or "").strip().upper().replace(" ", "")
            if line:
                lines.add(line)

        return sorted(lines)

    def _attach_alerts(self, result, alerts_index):
        if not isinstance(result, dict):
            return result

        lines = self._extract_lines_from_estimacion(result.get("data", {}))
        alerts = []
        seen = set()

        max_alerts = int(self._entry_value("alerts_max_per_stop", DEFAULT_ALERTS_MAX_PER_STOP))

        for line in lines:
            for alert in alerts_index.get(line, []):
                if not isinstance(alert, dict):
                    continue
                signature = (
                    alert.get("id_publicacion"),
                    alert.get("title"),
                    alert.get("inicio"),
                    alert.get("fin"),
                )
                if signature in seen:
                    continue
                seen.add(signature)
                alerts.append(alert)
                if len(alerts) >= max_alerts:
                    break
            if len(alerts) >= max_alerts:
                break

        result["lines"] = lines
        result["alerts"] = alerts
        result["alerts_count"] = len(alerts)
        return result

    async def _async_update_data(self):
        try:
            results = {}
            updated_at = dt_util.utcnow().isoformat()
            alerts_index = {}
            alerts_lang = str(self._entry_value("alerts_lang", DEFAULT_ALERTS_LANG) or "es").lower()

            try:
                alerts_index = await self.api.get_line_alerts(lang=alerts_lang, logger=_LOGGER)
            except Exception as err:
                _LOGGER.warning("VigoBus: unable to refresh line alerts for lang=%s: %s", alerts_lang, err)
                if alerts_lang != "es":
                    try:
                        alerts_index = await self.api.get_line_alerts(lang="es", logger=_LOGGER)
                    except Exception:
                        alerts_index = {}

            try:
                # Cached for a day inside VigoBusApi, so this is cheap on every
                # scan cycle; keep the previous map on failure rather than
                # blanking out colors for a transient network error.
                self._line_colors = await self.api.get_line_colors(logger=_LOGGER) or self._line_colors
            except Exception:
                _LOGGER.debug("VigoBus: unable to refresh line colors, keeping previous values")

            for key, name, lat, lon in self._nearest_targets():
                entry = await self._resolve_nearest_target(
                    key, name, lat, lon, updated_at, alerts_index
                )
                if entry is not None:
                    results[key] = entry

            for stop in self._entry_value("extra_stops", []):
                stop_id = stop.get("id")
                name = stop.get("name")
                if not stop_id or not name:
                    continue

                results[name] = {
                    "stop": stop,
                    "stop_name": name,
                    "updated_at": updated_at,
                    "data": await self.api.get_estimacion(stop_id),
                }
                self._attach_alerts(results[name], alerts_index)

            for key, value in results.items():
                value["stale"] = False
                value["stale_reason"] = None
                value["stale_at"] = None
                value["last_success_at"] = updated_at
                value["last_error_at"] = self._last_error_at
                value["consecutive_failures"] = self._consecutive_failures

            self._last_success_at = updated_at
            self._consecutive_failures = 0
            for key, value in results.items():
                if key == "nearest" or key.startswith("nearest_"):
                    await self._maybe_send_notification(key, value)

            return results
        except (TimeoutError, ClientError) as err:
            _LOGGER.warning("Network error updating VigoBus data: %s", err)
            self._consecutive_failures += 1
            self._last_error_at = dt_util.utcnow().isoformat()
            return self._mark_results_stale(self.data or {}, "network")
        except Exception:
            _LOGGER.exception("Unexpected error updating VigoBus data")
            self._consecutive_failures += 1
            self._last_error_at = dt_util.utcnow().isoformat()
            return self._mark_results_stale(self.data or {}, "unexpected")
