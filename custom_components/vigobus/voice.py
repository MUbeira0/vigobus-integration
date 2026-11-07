"""Assist (voice) support: "when does the bus come?".

The ``VigoBusNextBus`` intent is registered by the integration. Home Assistant
only turns spoken sentences into intents from sentence files, so this
repository ships ready-made ones in ``custom_sentences/`` (copy that folder
into your Home Assistant config directory).
"""

import re
import unicodedata

from homeassistant.helpers import intent

try:  # Home Assistant 2026.x validates intent slots with probatio
    import probatio as vol
except ImportError:  # older releases use voluptuous
    import voluptuous as vol

from .const import DOMAIN
from .logic import estimaciones_for, normalize_line

INTENT_NEXT_BUS = "VigoBusNextBus"

_TEXT = {
    "es": {
        "none": "No encuentro ninguna parada de VigoBus.",
        "unknown_stop": "No encuentro la parada {stop}.",
        "no_buses": "No hay autobuses previstos en {stop}.",
        "no_line": "No hay autobuses de la línea {line} previstos en {stop}.",
        "next": "En {stop}, el {line} llega en {minutes}.",
        "next_now": "En {stop}, el {line} llega ahora mismo.",
        "then": "Después, el {line} en {minutes}.",
        "then_now": "Después, el {line} ahora mismo.",
        "min_one": "{n} minuto",
        "min_many": "{n} minutos",
    },
    "gl": {
        "none": "Non atopo ningunha parada de VigoBus.",
        "unknown_stop": "Non atopo a parada {stop}.",
        "no_buses": "Non hai autobuses previstos en {stop}.",
        "no_line": "Non hai autobuses da liña {line} previstos en {stop}.",
        "next": "En {stop}, o {line} chega en {minutes}.",
        "next_now": "En {stop}, o {line} chega agora mesmo.",
        "then": "Despois, o {line} en {minutes}.",
        "then_now": "Despois, o {line} agora mesmo.",
        "min_one": "{n} minuto",
        "min_many": "{n} minutos",
    },
    "en": {
        "none": "I can't find any VigoBus stop.",
        "unknown_stop": "I can't find the stop {stop}.",
        "no_buses": "No buses are expected at {stop}.",
        "no_line": "No line {line} buses are expected at {stop}.",
        "next": "At {stop}, the {line} arrives in {minutes}.",
        "next_now": "At {stop}, the {line} is arriving right now.",
        "then": "Then the {line} in {minutes}.",
        "then_now": "Then the {line} right now.",
        "min_one": "{n} minute",
        "min_many": "{n} minutes",
    },
}


def _texts(language):
    return _TEXT.get(str(language or "es").lower()[:2], _TEXT["es"])


def _minutes_text(texts, minutes):
    key = "min_one" if minutes == 1 else "min_many"
    return texts[key].format(n=minutes)


# Words people (and small language models) use for "my home stop".
_HOME_WORDS = {
    "casa",
    "micasa",
    "encasa",
    "home",
    "myhome",
    "aqui",
    "miparada",
    "laparada",
    "paradadecasa",
    "laparadadecasa",
    "cerca",
}

# A bus line code: 25, 18A, C1, A...
_LINE_RE = re.compile(r"^(?:\d{1,3}[a-z]?\d?|[a-z]\d{1,2}|[a-z]{1,2})$", re.IGNORECASE)
_LINE_PREFIX_RE = re.compile(r"^(?:el|la|linea|línea|bus|autobus|autobús)\s+", re.IGNORECASE)
_LINE_IN_STOP_RE = re.compile(r"^(?:el\s+|la\s+)?(\S+)\s+(?:por|en|a|hasta|de)\s+(.+)$", re.IGNORECASE)


def clean_slots(stop, line):
    """Forgive the mistakes small language models make when filling the slots.

    Returns ``(stop, line)`` where ``stop`` is empty for the home stop. It
    handles a line given as the stop ("Urzaiz" in ``line``), both packed into
    ``stop`` ("25 por casa") and the many ways of saying "home".
    """
    stop = str(stop or "").strip()
    line = _LINE_PREFIX_RE.sub("", str(line or "").strip()).strip()

    match = _LINE_IN_STOP_RE.match(stop)
    if match and not line and _LINE_RE.match(match.group(1)):
        line, stop = match.group(1), match.group(2).strip()

    if line and not _LINE_RE.match(line):
        # Not a line code: the model most likely put the stop name here.
        if not stop:
            stop = line
        line = ""

    if _norm(stop) in _HOME_WORDS:
        stop = ""
    return stop, line


def _norm(value):
    text = unicodedata.normalize("NFD", str(value or "").lower())
    return "".join(ch for ch in text if ch.isalnum() and unicodedata.category(ch) != "Mn")


def find_stop(hass, wanted):
    """Return ``(coordinator, key, result)`` for the stop that best matches.

    With no ``wanted`` text it returns the first home "nearest" stop, falling
    back to any configured stop. Matching is accent- and punctuation-
    insensitive and accepts a substring of the stop name.
    """
    coordinators = [c for c in (hass.data.get(DOMAIN) or {}).values() if getattr(c, "data", None)]
    wanted_norm = _norm(wanted)

    if not wanted_norm:
        for coordinator in coordinators:
            if "nearest" in coordinator.data:
                return coordinator, "nearest", coordinator.data["nearest"]
        for coordinator in coordinators:
            for key, result in coordinator.data.items():
                return coordinator, key, result
        return None

    best = None
    for coordinator in coordinators:
        for key, result in coordinator.data.items():
            name = _norm((result or {}).get("stop_name") or key)
            if not name:
                continue
            if name == wanted_norm:
                return coordinator, key, result
            if wanted_norm in name and best is None:
                best = (coordinator, key, result)
    return best


def build_answer(result, key, line_filter, language):
    """The spoken answer for one stop result."""
    texts = _texts(language)
    stop_name = (result or {}).get("stop_name") or key
    buses = estimaciones_for(result, line_filter)
    if not buses:
        if line_filter:
            return texts["no_line"].format(stop=stop_name, line=normalize_line(line_filter))
        return texts["no_buses"].format(stop=stop_name)

    first = buses[0]
    if first["minutos"] <= 0:
        answer = texts["next_now"].format(stop=stop_name, line=first["linea"])
    else:
        answer = texts["next"].format(
            stop=stop_name, line=first["linea"], minutes=_minutes_text(texts, first["minutos"])
        )
    if len(buses) > 1:
        second = buses[1]
        if second["minutos"] <= 0:
            answer += " " + texts["then_now"].format(line=second["linea"])
        else:
            answer += " " + texts["then"].format(
                line=second["linea"], minutes=_minutes_text(texts, second["minutos"])
            )
    return answer


class NextBusIntentHandler(intent.IntentHandler):
    """Answers "when does the bus come (at <stop>)?"."""

    intent_type = INTENT_NEXT_BUS
    description = "Tells when the next VigoBus bus arrives at a stop"
    slot_schema = {
        vol.Optional(
            "stop",
            description="Name of the bus stop the user said. Leave empty for the user's home stop.",
        ): str,
        vol.Optional(
            "line",
            description="Bus line code the user said, for example 25, C1 or 18A. Leave empty if none.",
        ): str,
    }

    async def async_handle(self, intent_obj):
        slots = self.async_validate_slots(intent_obj.slots)
        wanted_stop, line = clean_slots(
            (slots.get("stop") or {}).get("value", ""),
            (slots.get("line") or {}).get("value", ""),
        )
        language = intent_obj.language

        response = intent_obj.create_response()
        texts = _texts(language)

        found = find_stop(intent_obj.hass, wanted_stop)
        if found is None:
            text = texts["unknown_stop"].format(stop=wanted_stop) if wanted_stop else texts["none"]
        else:
            _coordinator, key, result = found
            text = build_answer(result, key, line, language)

        response.async_set_speech(text)
        return response
