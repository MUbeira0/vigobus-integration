import logging
from datetime import timedelta

from aiohttp import ClientError

from homeassistant.components import persistent_notification
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
)

from .api import VigoBusApi
from .const import (
    DEFAULT_ALERTS_LANG,
    DEFAULT_ALERTS_MAX_PER_STOP,
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

        self.closest_stop = None
        self._last_success_at = None
        self._last_error_at = None
        self._consecutive_failures = 0
        self._last_notification_at = {}
        self._nearest_home_lat = None
        self._nearest_home_lon = None
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

    def _should_refresh_nearest(self, lat, lon):
        if self.closest_stop is None:
            return True

        if self._nearest_home_lat is None or self._nearest_home_lon is None:
            return True

        moved_m = self.api.haversine(self._nearest_home_lat, self._nearest_home_lon, lat, lon)
        return moved_m >= self._nearest_recalc_distance_m

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
            home = self.hass.states.get("zone.home")
            lat = None
            lon = None
            if home:
                lat = home.attributes.get("latitude")
                lon = home.attributes.get("longitude")
            else:
                _LOGGER.warning("zone.home is not available yet, using HA config coordinates")

            if lat is None or lon is None:
                lat = self.hass.config.latitude
                lon = self.hass.config.longitude

            if lat is None or lon is None:
                _LOGGER.warning("No coordinates available from zone.home or hass.config")
                return self.data or {}

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

            if self._entry_value("auto_nearest", True):
                if self._should_refresh_nearest(lat, lon):
                    self.closest_stop = await self.api.get_nearest_stop(lat, lon, logger=_LOGGER)
                    if self.closest_stop:
                        self._nearest_home_lat = lat
                        self._nearest_home_lon = lon

                if self.closest_stop:
                    stop_id = self._extract_stop_id(self.closest_stop)
                    if stop_id is not None:
                        nearest_name = str(self._entry_value("nearest_name", "") or "").strip()
                        results["nearest"] = {
                            "stop": self.closest_stop,
                            "stop_name": nearest_name,
                            "updated_at": updated_at,
                            "data": await self.api.get_estimacion(stop_id),
                        }
                        self._attach_alerts(results["nearest"], alerts_index)
                    else:
                        _LOGGER.warning("Nearest stop found but no stop ID key was detected")
                else:
                    _LOGGER.warning("No nearest stop could be resolved from paradas payload")

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
            await self._maybe_send_notification("nearest", results.get("nearest"))

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
