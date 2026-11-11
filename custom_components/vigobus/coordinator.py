import asyncio
import logging
import time
from collections import deque
from datetime import timedelta

from aiohttp import ClientError
from homeassistant.components import persistent_notification
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from . import gtfs
from .api import VigoBusApi
from .const import (
    COMMUTE_DAYS,
    DEFAULT_ALERTS_LANG,
    DEFAULT_ALERTS_MAX_PER_STOP,
    DEFAULT_AUTO_NEAREST_DEVICES,
    DEFAULT_COMMUTE_LEAD_MIN,
    DEFAULT_NEAREST_FALLBACK_RADIUS_M,
    DEFAULT_NEAREST_RECALC_DISTANCE_M,
    DEFAULT_NOTIFY_COOLDOWN_MIN,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_NOTIFY_LEAVE_NOW,
    DEFAULT_NOTIFY_MINUTES,
    DEFAULT_NOTIFY_NEW_ALERTS_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WALK_BUFFER_MIN,
    DOMAIN,
    ISSUE_ALERTS_FEED,
    ISSUE_STOP_MISSING,
    RELIABILITY_WINDOW,
    SIGNAL_ALERT_LIFECYCLE,
    SIGNAL_NEW_ALERTS,
    STOP_CHECK_INTERVAL_SECONDS,
)
from .logic import (
    alert_key,
    alert_status,
    compute_leave,
    estimaciones_for,
    live_counts,
    split_lines_text,
    walk_minutes,
)

_LOGGER = logging.getLogger(__name__)

# Consecutive good scans an alert must be absent before it is forgotten.
ALERT_FORGET_CYCLES = 3

# When the closest stop has no buses at all (a stop nothing serves right now),
# the "nearest" sensor looks at other stops within the configured radius of it.
NEAREST_FALLBACK_MAX_CANDIDATES = 12
# After a fallback search finds nothing, don't repeat it on every scan.
NEAREST_FALLBACK_RETRY_SECONDS = 120
# Failed alert scans in a row before a repair issue is raised.
ALERTS_FEED_ISSUE_THRESHOLD = 5

# After this many consecutive failures, start backing off from the
# configured scan_interval instead of retrying at full speed against a
# backend that's clearly down — being a better citizen toward a public API
# with no authentication/rate-limit contract, and reducing pointless "stale"
# churn during an outage.
BACKOFF_START_AFTER_FAILURES = 3
BACKOFF_MAX_SECONDS = 600


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
        # Snapshot of alert keys seen as of the last cycle, used to detect
        # newly-appeared alerts. _alerts_baseline_done gates the very first
        # cycle after (re)creating the coordinator (HA restart, or an options
        # save which reloads the entry): it just records what's already
        # active without notifying, so that moment doesn't get reported as a
        # flood of "new" alerts.
        self._notified_alert_ids = set()
        self._alerts_baseline_done = False
        # How many consecutive good scans each known alert has been missing
        # from. An alert is only forgotten (and so announced again if it comes
        # back) after ALERT_FORGET_CYCLES, so one stop failing to load for a
        # cycle doesn't make its alerts look new on the next one.
        self._alert_missing = {}
        # Last alert index that was fetched successfully; reused when the feed
        # is down so alerts don't blink out of the sensors.
        self._last_alerts_index = {}
        # Last version of every known alert, to report alert_started/alert_ended.
        self._alert_last = {}
        self._fallback_retry_at = {}
        self._alerts_feed_failures = 0
        self._alerts_feed_issue = False
        self._gtfs_warm_requested = False
        # Automation features: leave-now notifications, commute profiles,
        # live-reliability history and the periodic "does this stop still
        # exist" check that feeds Repairs.
        self._last_leave_notified = {}
        self._commute_done = {}
        self.commute_results = {}
        self._reliability = {}
        self._last_stop_check = None
        self._issues_created = set()
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
        self._base_update_interval = timedelta(seconds=scan_interval)

        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=self._base_update_interval,
            config_entry=entry,
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

        data = await self.api.get_estimacion(stop_id)
        fallback = None
        no_service = None
        original_stop = stop
        if not estimaciones_for({"data": data}):
            found = await self._fallback_stop_with_buses(key, lat, lon, stop_id)
            if found:
                fallback_stop, data = found
                fallback = {
                    "from_stop_id": stop_id,
                    "stop_id": self._extract_stop_id(fallback_stop),
                    "stop_name": fallback_stop.get("nombre") or fallback_stop.get("name"),
                }
                stop = fallback_stop
            else:
                no_service = self._no_service_info(original_stop)

        entry = {
            "stop": stop,
            "stop_name": name,
            "display_name": name,
            "updated_at": updated_at,
            "data": data,
        }
        if fallback:
            entry["fallback"] = fallback
        if no_service:
            entry["no_service"] = no_service
        stop_lat = stop.get("latitud")
        stop_lon = stop.get("longitud")
        if stop_lat is not None and stop_lon is not None:
            try:
                entry["walk_distance_m"] = round(
                    self.api.haversine(lat, lon, float(stop_lat), float(stop_lon))
                )
            except (TypeError, ValueError):
                pass
        self._attach_alerts(entry, alerts_index)
        return entry

    async def _fallback_stop_with_buses(self, key, lat, lon, tried_stop_id):
        """Closest other stop that currently has buses, or None.

        Only used when the closest stop returns nothing, so a nearest sensor
        doesn't sit on "unknown" next to a stop that does have service. The
        closest stop is still tried first on every scan: this never replaces
        the stop the sensor is anchored to, it only borrows another one for
        the scan when the anchor is empty.

        ``nearest_fallback_radius_m`` (0 = off) is how far beyond the closest
        stop to look. The candidates are queried together, and a search that
        finds nothing isn't repeated for a couple of minutes.
        """
        radius = int(self._entry_value("nearest_fallback_radius_m", DEFAULT_NEAREST_FALLBACK_RADIUS_M) or 0)
        if radius <= 0:
            return None
        if time.monotonic() < self._fallback_retry_at.get(key, 0.0):
            return None

        try:
            candidates = await self.api.get_nearest_stops(
                lat, lon, margin_m=radius, max_candidates=NEAREST_FALLBACK_MAX_CANDIDATES
            )
        except Exception as err:
            _LOGGER.debug("VigoBus: nearest fallback candidates unavailable: %s", err)
            return None

        todo = []
        for candidate in candidates:
            candidate_id = self._extract_stop_id(candidate)
            if candidate_id is None or str(candidate_id) == str(tried_stop_id):
                continue
            todo.append((candidate, candidate_id))

        results = await asyncio.gather(
            *(self.api.get_estimacion(candidate_id) for _candidate, candidate_id in todo),
            return_exceptions=True,
        )
        for (candidate, candidate_id), data in zip(todo, results):
            if isinstance(data, BaseException):
                _LOGGER.debug("VigoBus: nearest fallback stop %s failed: %s", candidate_id, data)
                continue
            if estimaciones_for({"data": data}):
                return candidate, data

        self._fallback_retry_at[key] = time.monotonic() + NEAREST_FALLBACK_RETRY_SECONDS
        return None

    def _no_service_info(self, stop):
        """Why a stop shows no buses: the lines that serve it and, when the
        schedule is already loaded, when the next one is due."""
        if not isinstance(stop, dict):
            return None
        info = {"serving_lines": split_lines_text(stop.get("lineas"))}

        index = gtfs.cached_index()
        if index is None:
            self._request_gtfs_warmup()
            return info

        now = dt_util.now()
        departures = gtfs.next_departures(
            index,
            str(stop.get("stop_id") or ""),
            now.strftime("%Y%m%d"),
            now.hour * 3600 + now.minute * 60 + now.second,
            limit=1,
        )
        if departures:
            first = departures[0]
            seconds = int(first["seconds"]) % 86400
            info["next_scheduled"] = {
                "time": f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}",
                "line": first["line"],
                "headsign": first["headsign"],
                "tomorrow": bool(first["next_day"]),
            }
        return info

    def _request_gtfs_warmup(self):
        """Load the schedule in the background, once, so later scans can use it."""
        if self._gtfs_warm_requested or not hasattr(self.hass, "async_create_task"):
            return
        self._gtfs_warm_requested = True

        async def _warm():
            try:
                await gtfs.get_gtfs_index(async_get_clientsession(self.hass), logger=_LOGGER)
            except Exception as err:
                _LOGGER.debug("VigoBus: schedule not available for the no-service hint: %s", err)

        self.hass.async_create_task(_warm())

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

    async def _dispatch_notification(self, title, message, notification_id):
        """Create the persistent notification, then mirror it to any of the
        user's chosen notify targets (e.g. a phone's mobile_app), if set.

        Targets come from the "notify_targets" option (Configure ->
        Notifications), populated from whatever notify services/entities
        this Home Assistant instance actually has registered. A target
        containing a "." is a notify *entity* (HA 2024.7+, sent via
        notify.send_message); anything else is a legacy notify.<service>
        name (e.g. mobile_app_my_phone) \u2014 both forms coexist across HA
        versions, so both are supported.
        """
        persistent_notification.async_create(
            self.hass,
            message,
            title=title,
            notification_id=notification_id,
        )

        for target in list(self._entry_value("notify_targets", []) or []):
            target = str(target or "").strip()
            if not target:
                continue
            try:
                if "." in target:
                    await self.hass.services.async_call(
                        "notify",
                        "send_message",
                        {"entity_id": target, "title": title, "message": message},
                        blocking=False,
                    )
                else:
                    await self.hass.services.async_call(
                        "notify",
                        target,
                        {"title": title, "message": message},
                        blocking=False,
                    )
            except Exception as err:
                _LOGGER.warning("VigoBus: fallo al notificar a %s: %s", target, err)

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
        await self._dispatch_notification(
            title, message, f"vigobus_alert_{self.entry.entry_id}_{stop_key}"
        )
        self._last_notification_at[stop_key] = now

    async def _maybe_notify_new_alerts(self, results, fresh=True):
        """Detect alerts that were not present on the previous scan.

        Detection always runs, so automations can react through the alert
        event entity even when notifications are off. The notification itself
        is still opt-in.

        ``fresh`` is False when the alerts feed could not be refreshed this
        cycle: nothing is learned from a stale snapshot, so the known set is
        left untouched instead of being emptied (which would re-announce every
        alert once the feed came back).
        """
        if not fresh:
            return

        current = {}
        for value in results.values():
            for alert in value.get("alerts", []) or []:
                if isinstance(alert, dict):
                    current[alert_key(alert)] = alert

        if not self._alerts_baseline_done:
            self._notified_alert_ids = set(current.keys())
            self._alert_missing = {}
            self._alert_last = dict(current)
            self._alerts_baseline_done = True
            return

        new_alerts = [alert for key, alert in current.items() if key not in self._notified_alert_ids]

        lifecycle = []
        for key, alert in current.items():
            previous = self._alert_last.get(key)
            if previous and previous.get("status") == "upcoming" and alert.get("status") == "active":
                lifecycle.append(("alert_started", alert))

        for key in list(self._notified_alert_ids):
            if key in current:
                self._alert_missing.pop(key, None)
                continue
            missing = self._alert_missing.get(key, 0) + 1
            if missing >= ALERT_FORGET_CYCLES:
                self._notified_alert_ids.discard(key)
                self._alert_missing.pop(key, None)
                ended = self._alert_last.pop(key, None)
                if ended:
                    lifecycle.append(("alert_ended", ended))
            else:
                self._alert_missing[key] = missing
        self._notified_alert_ids.update(current.keys())
        self._alert_last.update(current)

        if lifecycle:
            async_dispatcher_send(self.hass, SIGNAL_ALERT_LIFECYCLE.format(self.entry.entry_id), lifecycle)

        if not new_alerts:
            return

        async_dispatcher_send(self.hass, SIGNAL_NEW_ALERTS.format(self.entry.entry_id), new_alerts)

        if not bool(
            self._entry_value("notify_new_alerts_enabled", DEFAULT_NOTIFY_NEW_ALERTS_ENABLED)
        ):
            return

        if len(new_alerts) == 1:
            alert = new_alerts[0]
            title = "VigoBus: nuevo aviso"
            message = f"{alert.get('title') or 'Aviso'} ({alert.get('lineas') or '-'})"
        else:
            title = f"VigoBus: {len(new_alerts)} avisos nuevos"
            message = "\n".join(
                f"- {alert.get('title') or 'Aviso'} ({alert.get('lineas') or '-'})"
                for alert in new_alerts
            )

        await self._dispatch_notification(
            title, message, f"vigobus_new_alerts_{self.entry.entry_id}"
        )

    # ------------------------------------------------------------------
    # Leave-now
    # ------------------------------------------------------------------

    def _line_filter_for(self, key):
        if key == "nearest":
            return str(self._entry_value("nearest_line_filter", "") or "").strip()
        return ""

    def leave_info(self, key, line_filter=None):
        """Walk time and leave-in minutes for a nearest target, or None."""
        result = (self.data or {}).get(key)
        if not isinstance(result, dict):
            return None
        distance = result.get("walk_distance_m")
        if distance is None:
            return None
        if line_filter is None:
            line_filter = self._line_filter_for(key)
        walk_min = walk_minutes(distance)
        buffer_min = int(self._entry_value("walk_buffer_min", DEFAULT_WALK_BUFFER_MIN))
        info = compute_leave(estimaciones_for(result, line_filter), walk_min, buffer_min)
        if info is None:
            return None
        info["walk_min"] = walk_min
        info["buffer_min"] = buffer_min
        info["distance_m"] = distance
        return info

    async def _maybe_notify_leave_now(self, key, result):
        if not bool(self._entry_value("notify_leave_now", DEFAULT_NOTIFY_LEAVE_NOW)):
            return

        distance = result.get("walk_distance_m")
        if distance is None:
            return
        walk_min = walk_minutes(distance)
        buffer_min = int(self._entry_value("walk_buffer_min", DEFAULT_WALK_BUFFER_MIN))
        info = compute_leave(
            estimaciones_for(result, self._line_filter_for(key)), walk_min, buffer_min
        )
        if not info or info["leave_in"] is None or info["leave_in"] > 0:
            return

        now = dt_util.utcnow()
        last = self._last_leave_notified.get(key)
        cooldown_min = int(self._entry_value("notify_cooldown_min", DEFAULT_NOTIFY_COOLDOWN_MIN))
        if last is not None and (now - last).total_seconds() < cooldown_min * 60:
            return

        bus = info["bus"]
        stop_name = result.get("stop_name") or key
        message = (
            f"Sal ya hacia {stop_name}: el {bus['linea']} llega en {bus['minutos']} min "
            f"y tardas unos {walk_min} min andando."
        )
        await self._dispatch_notification(
            "VigoBus: sal ya", message, f"vigobus_leave_{self.entry.entry_id}_{key}"
        )
        self._last_leave_notified[key] = now

    # ------------------------------------------------------------------
    # Live reliability / service status
    # ------------------------------------------------------------------

    def _record_reliability(self, results):
        for key, value in results.items():
            live, total = live_counts(value)
            if total == 0:
                continue
            window = self._reliability.setdefault(key, deque(maxlen=RELIABILITY_WINDOW))
            window.append((live, total))

    def reliability_pct(self, key):
        """Share (0-100) of listed buses with a live GPS position over the
        recent scans, or None when there is no history yet."""
        window = self._reliability.get(key)
        if not window:
            return None
        live = sum(item[0] for item in window)
        total = sum(item[1] for item in window)
        if total == 0:
            return None
        return round(100 * live / total)

    @property
    def service_status(self):
        """One word for the health of the data: ok / alerts / degraded / offline."""
        if self._consecutive_failures >= 3:
            return "offline"
        if self._consecutive_failures > 0:
            return "degraded"
        for value in (self.data or {}).values():
            if isinstance(value, dict) and value.get("alerts_count"):
                return "alerts"
        return "ok"

    # ------------------------------------------------------------------
    # Commute profiles
    # ------------------------------------------------------------------

    def _commute_origin(self, origin):
        if not origin or origin == "home":
            return self._home_coords()
        state = self.hass.states.get(origin)
        if not state:
            return None, None
        return state.attributes.get("latitude"), state.attributes.get("longitude")

    async def _maybe_run_commutes(self):
        """Plan each commute once per day, shortly before its usual departure."""
        commutes = list(self._entry_value("commutes", []) or [])
        if not commutes:
            self.commute_results = {}
            return

        now_local = dt_util.now()
        weekday = COMMUTE_DAYS[now_local.weekday()]
        today = now_local.strftime("%Y%m%d")
        now_minutes = now_local.hour * 60 + now_local.minute

        names = {str(c.get("name") or "").strip() for c in commutes}
        self.commute_results = {k: v for k, v in self.commute_results.items() if k in names}

        for commute in commutes:
            name = str(commute.get("name") or "").strip()
            if not name or weekday not in (commute.get("days") or COMMUTE_DAYS):
                continue
            try:
                hh, mm = str(commute.get("time") or "").split(":")[:2]
                depart_minutes = int(hh) * 60 + int(mm)
            except (ValueError, TypeError):
                continue

            lead = int(commute.get("lead_min") or DEFAULT_COMMUTE_LEAD_MIN)
            if not (depart_minutes - lead <= now_minutes <= depart_minutes):
                continue
            if self._commute_done.get(name) == today:
                continue

            self._commute_done[name] = today
            lat, lon = self._commute_origin(commute.get("origin"))
            if lat is None or lon is None:
                _LOGGER.warning("VigoBus: commute %s has no usable origin", name)
                continue

            from . import plan_trip_handler

            try:
                plan = await plan_trip_handler(
                    self.hass,
                    {
                        "origin_latitude": float(lat),
                        "origin_longitude": float(lon),
                        "destination_stop_id": str(commute.get("destination_stop_id")),
                        "depart_at": f"{hh}:{mm}",
                        "max_transfers": 1,
                        "max_itineraries": 1,
                        "include_live": True,
                    },
                )
            except Exception as err:
                _LOGGER.warning("VigoBus: unable to plan commute %s: %s", name, err)
                continue

            itineraries = plan.get("itineraries") or []
            if not itineraries:
                continue
            best = itineraries[0]
            lines = ", ".join(best.get("lines") or [])
            summary = (
                f"{name}: sal a las {best.get('depart')}, llegas a las {best.get('arrive')} "
                f"({best.get('duration_min')} min, líneas {lines or '-'})."
            )
            self.commute_results[name] = {
                "depart": best.get("depart"),
                "arrive": best.get("arrive"),
                "duration_min": best.get("duration_min"),
                "lines": best.get("lines") or [],
                "transfers": best.get("transfers"),
                "summary": summary,
                "planned_at": dt_util.utcnow().isoformat(),
                "destination": commute.get("destination_name") or commute.get("destination_stop_id"),
            }
            await self._dispatch_notification(
                "VigoBus: tu trayecto",
                summary,
                f"vigobus_commute_{self.entry.entry_id}_{slugify(name)}",
            )

    # ------------------------------------------------------------------
    # Repairs
    # ------------------------------------------------------------------

    async def _maybe_check_stops(self):
        """Raise a Repairs issue when a configured extra stop no longer exists
        in the Vigo stop catalog, so it can be removed with one click."""
        now = dt_util.utcnow()
        if (
            self._last_stop_check is not None
            and (now - self._last_stop_check).total_seconds() < STOP_CHECK_INTERVAL_SECONDS
        ):
            return
        self._last_stop_check = now

        extra_stops = [
            stop for stop in (self._entry_value("extra_stops", []) or []) if stop.get("id")
        ]

        from .stop_catalog import _build_catalog_id_index, _get_catalog_stops, _normalize_text

        try:
            catalog = await _get_catalog_stops(self.hass)
        except Exception:
            return
        if not catalog:
            # An empty catalog means the lookup failed, not that every stop
            # vanished: never raise issues from that.
            return

        id_index = _build_catalog_id_index(catalog)
        wanted = set()
        for stop in extra_stops:
            stop_id = str(stop["id"]).strip()
            issue_id = f"{ISSUE_STOP_MISSING}_{self.entry.entry_id}_{stop_id}"
            if _normalize_text(stop_id) in id_index:
                continue
            wanted.add(issue_id)
            if issue_id in self._issues_created:
                continue
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_STOP_MISSING,
                translation_placeholders={
                    "name": str(stop.get("name") or stop_id),
                    "stop_id": stop_id,
                },
                data={"entry_id": self.entry.entry_id, "stop_id": stop_id},
            )

        for issue_id in list(self._issues_created - wanted):
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._issues_created = wanted

    def _track_alerts_feed(self, fresh):
        """Raise a repair issue when the alerts feed keeps failing; clear it on recovery."""
        issue_id = f"{ISSUE_ALERTS_FEED}_{self.entry.entry_id}"
        if fresh:
            self._alerts_feed_failures = 0
            if self._alerts_feed_issue:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                self._alerts_feed_issue = False
            return

        self._alerts_feed_failures += 1
        if self._alerts_feed_failures >= ALERTS_FEED_ISSUE_THRESHOLD and not self._alerts_feed_issue:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_ALERTS_FEED,
                translation_placeholders={"failures": str(self._alerts_feed_failures)},
            )
            self._alerts_feed_issue = True

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
        candidates = []
        seen = set()

        max_alerts = max(1, int(self._entry_value("alerts_max_per_stop", DEFAULT_ALERTS_MAX_PER_STOP)))
        today = dt_util.now().date()

        for line in lines:
            for alert in alerts_index.get(line, []):
                if not isinstance(alert, dict):
                    continue
                signature = alert_key(alert)
                if signature in seen:
                    continue
                status = alert_status(alert, today)
                if status == "expired":
                    continue
                seen.add(signature)
                candidates.append({**alert, "status": status})

        # Alerts in force go first (the sort is stable, so the line order is
        # otherwise kept), so the per-stop cap can never hide one of them
        # behind an upcoming alert that merely sorted earlier.
        candidates.sort(key=lambda alert: alert["status"] != "active")
        alerts = candidates[:max_alerts]

        result["lines"] = lines
        result["alerts"] = alerts
        # Only alerts in force count: upcoming ones are listed (status
        # "upcoming") but don't turn the service status into "alerts" yet.
        result["alerts_count"] = sum(1 for alert in alerts if alert.get("status") == "active")
        return result

    async def _async_update_data(self):
        try:
            results = {}
            updated_at = dt_util.utcnow().isoformat()
            alerts_index = {}
            alerts_fresh = False
            alerts_lang = str(self._entry_value("alerts_lang", DEFAULT_ALERTS_LANG) or "es").lower()

            try:
                alerts_index = await self.api.get_line_alerts(lang=alerts_lang, logger=_LOGGER)
                alerts_fresh = True
            except Exception as err:
                _LOGGER.warning("VigoBus: unable to refresh line alerts for lang=%s: %s", alerts_lang, err)
                if alerts_lang != "es":
                    try:
                        alerts_index = await self.api.get_line_alerts(lang="es", logger=_LOGGER)
                        alerts_fresh = True
                    except Exception:
                        pass

            self._track_alerts_feed(alerts_fresh)
            if alerts_fresh:
                self._last_alerts_index = alerts_index
            else:
                # Keep showing the last alerts we know about instead of
                # blanking them out for a transient feed failure.
                alerts_index = self._last_alerts_index

            try:
                # Cached for a day inside VigoBusApi, so this is cheap on every
                # scan cycle; keep the previous map on failure rather than
                # blanking out colors for a transient network error.
                self._line_colors = await self.api.get_line_colors(logger=_LOGGER) or self._line_colors
            except Exception:
                _LOGGER.debug("VigoBus: unable to refresh line colors, keeping previous values")

            # Each target/extra stop is an independent HTTP round trip, so
            # resolve them concurrently instead of one at a time — this
            # matters most with several tracked people/devices, where a
            # sequential loop meant the scan took proportionally longer for
            # every device added. return_exceptions=True also means one
            # flaky target (e.g. a device with a temperamental connection)
            # no longer blanks out every other stop's data for the cycle.
            targets = self._nearest_targets()
            resolved_targets = await asyncio.gather(
                *(
                    self._resolve_nearest_target(key, name, lat, lon, updated_at, alerts_index)
                    for key, name, lat, lon in targets
                ),
                return_exceptions=True,
            )
            for (key, _name, _lat, _lon), entry in zip(targets, resolved_targets):
                if isinstance(entry, BaseException):
                    _LOGGER.warning("VigoBus: fallo al actualizar target %s: %s", key, entry)
                    continue
                if entry is not None:
                    results[key] = entry

            extra_stops = [
                stop
                for stop in self._entry_value("extra_stops", [])
                if stop.get("id") and stop.get("name")
            ]

            async def _resolve_extra_stop(stop):
                data = await self.api.get_estimacion(stop.get("id"))
                entry = {
                    "stop": stop,
                    "stop_name": stop.get("name"),
                    "updated_at": updated_at,
                    "data": data,
                }
                self._attach_alerts(entry, alerts_index)
                return entry

            resolved_extra_stops = await asyncio.gather(
                *(_resolve_extra_stop(stop) for stop in extra_stops),
                return_exceptions=True,
            )
            for stop, entry in zip(extra_stops, resolved_extra_stops):
                if isinstance(entry, BaseException):
                    _LOGGER.warning(
                        "VigoBus: fallo al actualizar parada extra %s: %s", stop.get("name"), entry
                    )
                    continue
                results[stop.get("name")] = entry

            for key, value in results.items():
                value["stale"] = False
                value["stale_reason"] = None
                value["stale_at"] = None
                value["last_success_at"] = updated_at
                value["last_error_at"] = self._last_error_at
                value["consecutive_failures"] = self._consecutive_failures

            self._last_success_at = updated_at
            self._consecutive_failures = 0
            self.update_interval = self._base_update_interval
            for key, value in results.items():
                if key == "nearest" or key.startswith("nearest_"):
                    await self._maybe_send_notification(key, value)
                    await self._maybe_notify_leave_now(key, value)
            await self._maybe_notify_new_alerts(results, fresh=alerts_fresh)
            self._record_reliability(results)
            await self._maybe_run_commutes()
            await self._maybe_check_stops()

            return results
        except (TimeoutError, ClientError) as err:
            _LOGGER.warning("Network error updating VigoBus data: %s", err)
            self._consecutive_failures += 1
            self._last_error_at = dt_util.utcnow().isoformat()
            self._apply_backoff()
            return self._mark_results_stale(self.data or {}, "network")
        except Exception:
            _LOGGER.exception("Unexpected error updating VigoBus data")
            self._consecutive_failures += 1
            self._last_error_at = dt_util.utcnow().isoformat()
            self._apply_backoff()
            return self._mark_results_stale(self.data or {}, "unexpected")

    def _apply_backoff(self):
        """Slow down polling after repeated failures, reset on success.

        Retrying at the full configured rate against a backend that's
        clearly unreachable just adds load for no benefit. Doubles the
        interval starting at BACKOFF_START_AFTER_FAILURES consecutive
        failures, capped at BACKOFF_MAX_SECONDS; a single success (in
        _async_update_data's success path) resets it immediately.
        """
        if self._consecutive_failures < BACKOFF_START_AFTER_FAILURES:
            self.update_interval = self._base_update_interval
            return

        factor = 2 ** (self._consecutive_failures - BACKOFF_START_AFTER_FAILURES + 1)
        seconds = min(self._base_update_interval.total_seconds() * factor, BACKOFF_MAX_SECONDS)
        self.update_interval = timedelta(seconds=seconds)
