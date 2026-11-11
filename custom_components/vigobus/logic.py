"""Pure helpers shared by the coordinator, sensors and the voice intent.

Nothing in here touches Home Assistant or the network, so it is cheap to unit
test and safe to import from anywhere.
"""

import math
from datetime import date, timedelta

from .api import split_line_variant
from .const import WALK_DETOUR_FACTOR, WALK_SPEED_MPS


def normalize_line(value):
    return str(value or "").strip().upper().replace(" ", "")


def estimaciones_for(result, line_filter=""):
    """Valid upcoming buses of a stop result, soonest first.

    Returns a list of ``{"linea", "ruta", "minutos", "metros"}`` dicts. When
    ``line_filter`` is set, only buses of that line (matching either the base
    line or its variant, e.g. ``C1`` / ``C``) are kept.
    """
    data = (result or {}).get("data") or {}
    estimaciones = data.get("estimaciones", [])
    if not isinstance(estimaciones, list):
        return []

    wanted = normalize_line(line_filter)
    buses = []
    for bus in estimaciones:
        if not isinstance(bus, dict):
            continue
        try:
            minutos = int(bus.get("minutos"))
        except (TypeError, ValueError):
            continue

        eff_line, eff_route = split_line_variant(bus.get("linea"), bus.get("ruta"))
        if wanted and wanted not in (normalize_line(bus.get("linea")), normalize_line(eff_line)):
            continue

        buses.append(
            {
                "linea": eff_line,
                "ruta": eff_route,
                "minutos": minutos,
                "metros": bus.get("metros"),
            }
        )

    buses.sort(key=lambda item: item["minutos"])
    return buses


def live_counts(result):
    """(live_buses, total_buses) for a stop result.

    A bus counts as live when the feed reports a non-negative distance in
    metres (the bus has a GPS position); otherwise it is timetable-only.
    """
    data = (result or {}).get("data") or {}
    estimaciones = data.get("estimaciones", [])
    if not isinstance(estimaciones, list):
        return 0, 0

    live = 0
    total = 0
    for bus in estimaciones:
        if not isinstance(bus, dict):
            continue
        total += 1
        metros = bus.get("metros")
        if isinstance(metros, (int, float)) and not isinstance(metros, bool) and metros >= 0:
            live += 1
    return live, total


def walk_minutes(distance_m):
    """Estimated minutes to walk ``distance_m`` metres of straight-line distance."""
    try:
        distance = float(distance_m)
    except (TypeError, ValueError):
        return None
    if distance < 0 or math.isnan(distance):
        return None
    return math.ceil(distance * WALK_DETOUR_FACTOR / WALK_SPEED_MPS / 60)


def compute_leave(buses, walk_min, buffer_min=0):
    """Decide when to leave to catch a bus.

    ``buses`` is the output of :func:`estimaciones_for`. You need
    ``walk_min + buffer_min`` minutes to reach the stop, so the first bus that
    is at least that far away is the one you can catch.

    Returns ``None`` when there is no walk estimate or no bus at all,
    otherwise a dict with:

    * ``leave_in`` – minutes from now until you should leave (0 = leave now),
      or ``None`` when every listed bus is too close to catch,
    * ``bus`` – the bus you can catch (or ``None``),
    * ``missed`` – the first bus that is already too close to catch (or ``None``),
    * ``needed`` – minutes you need to reach the stop.
    """
    if walk_min is None or not buses:
        return None

    needed = walk_min + max(0, int(buffer_min or 0))
    missed = None
    for bus in buses:
        if bus["minutos"] < needed:
            if missed is None:
                missed = bus
            continue
        return {
            "leave_in": bus["minutos"] - needed,
            "bus": bus,
            "missed": missed,
            "needed": needed,
        }

    return {"leave_in": None, "bus": None, "missed": missed, "needed": needed}


def format_minutes_es(minutes):
    """"1 minuto" / "5 minutos" – used for spoken answers."""
    minutes = int(minutes)
    return f"{minutes} minuto" if minutes == 1 else f"{minutes} minutos"


# ----------------------------------------------------------------------
# Alerts
# ----------------------------------------------------------------------


def alert_key(alert):
    """Stable identity of an alert.

    The publication id is what the feed itself uses, so an alert whose title or
    dates get edited (typically an "ACTUALIZACI\u00d3N ..." of the same notice) is
    still the same alert. Only alerts without an id fall back to a signature.
    """
    alert = alert or {}
    pub_id = alert.get("id_publicacion")
    if pub_id:
        return ("id", str(pub_id))
    return ("sig", alert.get("title"), alert.get("inicio"), alert.get("fin"))


def parse_alert_date(value):
    """``YYYY-MM-DD`` or ``DD-MM-YYYY`` (the feed uses both) -> ``date`` or None."""
    text = str(value or "").strip()[:10]
    try:
        if len(text) == 10 and text[4] == "-":
            return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
        if len(text) == 10 and text[2] == "-":
            return date(int(text[6:10]), int(text[3:5]), int(text[0:2]))
    except ValueError:
        return None
    return None


def alert_status(alert, today):
    """``expired``, ``upcoming`` or ``active`` for ``today`` (a ``date``).

    An alert with a missing or unreadable date is treated as active, so a
    malformed record is never silently hidden.
    """
    start = parse_alert_date((alert or {}).get("inicio"))
    end = parse_alert_date((alert or {}).get("fin"))
    if end is not None and end < today:
        return "expired"
    if start is not None and start > today:
        return "upcoming"
    return "active"


def collect_alerts(results):
    """Distinct alerts across every stop, with the stops each one affects.

    ``results`` is the coordinator data (stop key -> stop result). The same
    alert shows up on every stop served by an affected line, so counting per
    stop inflates the number; this returns each alert once, active first and
    then by end date.
    """
    merged = {}
    for key, value in (results or {}).items():
        if not isinstance(value, dict):
            continue
        stop = value.get("stop_name") or key
        for alert in value.get("alerts") or []:
            if not isinstance(alert, dict):
                continue
            akey = alert_key(alert)
            entry = merged.get(akey)
            if entry is None:
                entry = dict(alert)
                entry["stops"] = []
                merged[akey] = entry
            if stop not in entry["stops"]:
                entry["stops"].append(stop)

    def _order(item):
        return (item.get("status") != "active", str(item.get("fin") or "9999"), str(item.get("title") or ""))

    return sorted(merged.values(), key=_order)


ALERT_KINDS = ("strike", "closure", "detour", "stop_closed", "works", "schedule", "info")


def alert_event_span(alert, today):
    """All-day span ``(start, end_exclusive)`` of an alert, or None if expired.

    Missing dates degrade gracefully: no start means "from today", no end
    means a single day.
    """
    start = parse_alert_date((alert or {}).get("inicio")) or today
    end = parse_alert_date((alert or {}).get("fin")) or start
    if end < start:
        end = start
    if end < today:
        return None
    return start, end + timedelta(days=1)


def split_lines_text(value):
    """``"25, 11"`` (or a list) -> ``["25", "11"]``."""
    if isinstance(value, (list, tuple, set)):
        raw = [str(item or "") for item in value]
    else:
        raw = str(value or "").replace(";", ",").split(",")
    return [part.strip() for part in raw if part.strip()]
