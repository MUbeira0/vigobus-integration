import voluptuous as vol
import unicodedata

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
    MAX_ALERTS_MAX_PER_STOP,
    MAX_NOTIFY_COOLDOWN_MIN,
    MAX_NOTIFY_MINUTES,
    MAX_NEAREST_RECALC_DISTANCE_M,
    MAX_SCAN_INTERVAL,
    MIN_NOTIFY_COOLDOWN_MIN,
    MIN_NOTIFY_MINUTES,
    MIN_NEAREST_RECALC_DISTANCE_M,
    MIN_ALERTS_MAX_PER_STOP,
    MIN_SCAN_INTERVAL,
)


def _serialize_extra_stops(extra_stops):
    lines = []
    for stop in extra_stops or []:
        stop_id = str(stop.get("id", "")).strip()
        name = str(stop.get("name", "")).strip()
        if stop_id and name:
            lines.append(f"{stop_id},{name}")
    return " | ".join(lines)


def _normalize_text(value):
    text = str(value or "").strip().lower()
    normalized = unicodedata.normalize("NFD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _extract_catalog_stop(stop):
    if not isinstance(stop, dict):
        return None

    properties = stop.get("properties") if isinstance(stop.get("properties"), dict) else {}

    stop_id = None
    for key in ("stop_id", "idparada", "parada", "id"):
        value = stop.get(key)
        if value is None:
            value = properties.get(key)
        if value is not None and str(value).strip():
            stop_id = str(value).strip()
            break

    if not stop_id:
        return None

    name = None
    for key in ("nombre", "name", "denominacion", "title", "descripcion", "label", "parada"):
        value = stop.get(key)
        if value is None:
            value = properties.get(key)
        if value is not None and str(value).strip():
            name = str(value).strip()
            break

    if not name:
        name = f"stop_{stop_id}"

    return {
        "id": stop_id,
        "name": name,
        "id_norm": _normalize_text(stop_id),
        "name_norm": _normalize_text(name),
    }


def _search_stop_by_text(query, catalog):
    query_norm = _normalize_text(query)
    if not query_norm:
        return None

    terms = [term for term in query_norm.split() if term]
    best = None
    best_score = None

    for stop in catalog:
        id_norm = stop["id_norm"]
        name_norm = stop["name_norm"]

        score = None
        if query_norm == id_norm:
            score = 0
        elif query_norm == name_norm:
            score = 1
        elif query_norm in name_norm:
            score = 10 + len(name_norm)
        elif terms and all(term in name_norm for term in terms):
            score = 20 + len(name_norm)

        if score is None:
            continue

        if best is None or score < best_score:
            best = stop
            best_score = score

    if best is None:
        return None

    return {"id": best["id"], "name": best["name"]}


async def _parse_extra_stops(hass, raw_value):
    extra_stops = []
    errors = False
    seen_ids = set()
    seen_names = set()

    raw = str(raw_value or "")
    records = []
    for line in raw.splitlines():
        parts = [part.strip() for part in line.split("|")]
        records.extend([part for part in parts if part])

    raw_entries = []
    needs_catalog = False

    for text in records:

        if "," in text:
            parts = text.split(",", 1)
        elif ";" in text:
            parts = text.split(";", 1)
        else:
            token = text.strip()
            if token.isdigit():
                raw_entries.append({"kind": "id", "id": token, "name": f"stop_{token}"})
            else:
                raw_entries.append({"kind": "search", "query": token})
            needs_catalog = True
            continue

        stop_id = parts[0].strip()
        name = parts[1].strip() or f"stop_{stop_id}"
        if not stop_id:
            errors = True
            continue

        raw_entries.append({"kind": "explicit", "id": stop_id, "name": name})

    catalog = []
    if needs_catalog:
        try:
            api = VigoBusApi(async_get_clientsession(hass))
            data = await api.get_paradas()
            stops = api._extract_stops(data)
            catalog = [item for item in (_extract_catalog_stop(stop) for stop in stops) if item]
        except Exception:
            catalog = []

    id_to_name = {item["id_norm"]: item["name"] for item in catalog}

    for entry in raw_entries:
        if entry["kind"] in ("explicit", "id"):
            stop_id = str(entry["id"]).strip()
            if not stop_id:
                errors = True
                continue

            name = str(entry.get("name") or "").strip()
            if entry["kind"] == "id":
                name = id_to_name.get(_normalize_text(stop_id), name)

            if not name:
                name = f"stop_{stop_id}"
        else:
            match = _search_stop_by_text(entry["query"], catalog)
            if not match:
                errors = True
                continue
            stop_id = match["id"]
            name = match["name"]

        key_id = stop_id.lower()
        key_name = name.lower()
        if key_id in seen_ids or key_name in seen_names:
            continue

        seen_ids.add(key_id)
        seen_names.add(key_name)
        extra_stops.append({"id": stop_id, "name": name})

    return extra_stops, errors


class VigoBusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            extra_stops, has_invalid_lines = await _parse_extra_stops(
                self.hass,
                user_input.get("extra_stops", ""),
            )
            if has_invalid_lines:
                errors["base"] = "invalid_extra_stops"

            if not errors:
                return self.async_create_entry(
                    title="VigoBus",
                    data={
                        "auto_nearest": user_input.get(
                            "auto_nearest",
                            True,
                        ),
                        "nearest_name": user_input.get("nearest_name", "").strip(),
                        "extra_stops": extra_stops,
                        "scan_interval": int(user_input.get("scan_interval", DEFAULT_SCAN_INTERVAL)),
                        "nearest_recalc_distance_m": int(
                            user_input.get(
                                "nearest_recalc_distance_m",
                                DEFAULT_NEAREST_RECALC_DISTANCE_M,
                            )
                        ),
                        "notify_enabled": bool(user_input.get("notify_enabled", DEFAULT_NOTIFY_ENABLED)),
                        "notify_minutes": int(user_input.get("notify_minutes", DEFAULT_NOTIFY_MINUTES)),
                        "notify_cooldown_min": int(
                            user_input.get("notify_cooldown_min", DEFAULT_NOTIFY_COOLDOWN_MIN)
                        ),
                        "alerts_lang": str(user_input.get("alerts_lang", DEFAULT_ALERTS_LANG)),
                        "alerts_max_per_stop": int(
                            user_input.get("alerts_max_per_stop", DEFAULT_ALERTS_MAX_PER_STOP)
                        ),
                    },
                )

        schema = vol.Schema(
            {
                vol.Optional("auto_nearest", default=True): bool,
                vol.Optional("nearest_name", default=""): str,
                vol.Optional(
                    "scan_interval",
                    default=DEFAULT_SCAN_INTERVAL,
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
                vol.Optional(
                    "nearest_recalc_distance_m",
                    default=DEFAULT_NEAREST_RECALC_DISTANCE_M,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_NEAREST_RECALC_DISTANCE_M,
                        max=MAX_NEAREST_RECALC_DISTANCE_M,
                    ),
                ),
                vol.Optional("notify_enabled", default=DEFAULT_NOTIFY_ENABLED): bool,
                vol.Optional("notify_minutes", default=DEFAULT_NOTIFY_MINUTES): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_NOTIFY_MINUTES, max=MAX_NOTIFY_MINUTES),
                ),
                vol.Optional("notify_cooldown_min", default=DEFAULT_NOTIFY_COOLDOWN_MIN): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_NOTIFY_COOLDOWN_MIN, max=MAX_NOTIFY_COOLDOWN_MIN),
                ),
                vol.Optional("alerts_lang", default=DEFAULT_ALERTS_LANG): vol.In(
                    ["es", "en", "gl"]
                ),
                vol.Optional("alerts_max_per_stop", default=DEFAULT_ALERTS_MAX_PER_STOP): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_ALERTS_MAX_PER_STOP, max=MAX_ALERTS_MAX_PER_STOP),
                ),
                vol.Optional(
                    "extra_stops",
                    default="",
                ): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return VigoBusOptionsFlow(config_entry)


class VigoBusOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._config_entry = config_entry
        self._draft = None
        self._catalog = None
        self._search_choices = {}
        self._pending_custom_name = ""

    def _entry_value(self, key, default=None):
        if self._draft is not None and key in self._draft:
            return self._draft.get(key, default)
        if key in self._config_entry.options:
            return self._config_entry.options.get(key)
        return self._config_entry.data.get(key, default)

    def _ensure_draft(self):
        if self._draft is not None:
            return

        self._draft = {
            "auto_nearest": bool(self._entry_value("auto_nearest", True)),
            "nearest_name": str(self._entry_value("nearest_name", "") or "").strip(),
            "extra_stops": list(self._entry_value("extra_stops", []) or []),
            "scan_interval": int(self._entry_value("scan_interval", DEFAULT_SCAN_INTERVAL)),
            "nearest_recalc_distance_m": int(
                self._entry_value("nearest_recalc_distance_m", DEFAULT_NEAREST_RECALC_DISTANCE_M)
            ),
            "notify_enabled": bool(self._entry_value("notify_enabled", DEFAULT_NOTIFY_ENABLED)),
            "notify_minutes": int(self._entry_value("notify_minutes", DEFAULT_NOTIFY_MINUTES)),
            "notify_cooldown_min": int(
                self._entry_value("notify_cooldown_min", DEFAULT_NOTIFY_COOLDOWN_MIN)
            ),
            "alerts_lang": str(self._entry_value("alerts_lang", DEFAULT_ALERTS_LANG)),
            "alerts_max_per_stop": int(
                self._entry_value("alerts_max_per_stop", DEFAULT_ALERTS_MAX_PER_STOP)
            ),
        }

    async def _load_catalog(self):
        if self._catalog is not None:
            return self._catalog

        api = VigoBusApi(async_get_clientsession(self.hass))
        data = await api.get_paradas()
        stops = api._extract_stops(data)
        self._catalog = [item for item in (_extract_catalog_stop(stop) for stop in stops) if item]
        return self._catalog

    async def async_step_init(self, user_input=None):
        self._ensure_draft()
        return self.async_show_menu(
            step_id="init",
            menu_options=["edit_general", "add_stop_search", "remove_stop", "finish"],
        )

    async def async_step_edit_general(self, user_input=None):
        self._ensure_draft()

        if user_input is not None:
            self._draft.update(
                {
                    "auto_nearest": bool(user_input.get("auto_nearest", True)),
                    "nearest_name": str(user_input.get("nearest_name", "")).strip(),
                    "scan_interval": int(user_input.get("scan_interval", DEFAULT_SCAN_INTERVAL)),
                    "nearest_recalc_distance_m": int(
                        user_input.get(
                            "nearest_recalc_distance_m",
                            DEFAULT_NEAREST_RECALC_DISTANCE_M,
                        )
                    ),
                    "notify_enabled": bool(user_input.get("notify_enabled", DEFAULT_NOTIFY_ENABLED)),
                    "notify_minutes": int(user_input.get("notify_minutes", DEFAULT_NOTIFY_MINUTES)),
                    "notify_cooldown_min": int(
                        user_input.get("notify_cooldown_min", DEFAULT_NOTIFY_COOLDOWN_MIN)
                    ),
                    "alerts_lang": str(user_input.get("alerts_lang", DEFAULT_ALERTS_LANG)),
                    "alerts_max_per_stop": int(
                        user_input.get("alerts_max_per_stop", DEFAULT_ALERTS_MAX_PER_STOP)
                    ),
                }
            )
            return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Optional("auto_nearest", default=self._draft["auto_nearest"]): bool,
                vol.Optional("nearest_name", default=self._draft["nearest_name"]): str,
                vol.Optional("scan_interval", default=self._draft["scan_interval"]): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Optional(
                    "nearest_recalc_distance_m",
                    default=self._draft["nearest_recalc_distance_m"],
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_NEAREST_RECALC_DISTANCE_M,
                        max=MAX_NEAREST_RECALC_DISTANCE_M,
                    ),
                ),
                vol.Optional("notify_enabled", default=self._draft["notify_enabled"]): bool,
                vol.Optional("notify_minutes", default=self._draft["notify_minutes"]): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_NOTIFY_MINUTES, max=MAX_NOTIFY_MINUTES),
                ),
                vol.Optional(
                    "notify_cooldown_min",
                    default=self._draft["notify_cooldown_min"],
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_NOTIFY_COOLDOWN_MIN, max=MAX_NOTIFY_COOLDOWN_MIN),
                ),
                vol.Optional("alerts_lang", default=self._draft["alerts_lang"]): vol.In(
                    ["es", "en", "gl"]
                ),
                vol.Optional(
                    "alerts_max_per_stop",
                    default=self._draft["alerts_max_per_stop"],
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_ALERTS_MAX_PER_STOP, max=MAX_ALERTS_MAX_PER_STOP),
                ),
            }
        )

        return self.async_show_form(step_id="edit_general", data_schema=schema, errors={})

    async def async_step_add_stop_search(self, user_input=None):
        self._ensure_draft()
        errors = {}

        if user_input is not None:
            query = str(user_input.get("search_query", "") or "").strip()
            custom_name = str(user_input.get("custom_name", "") or "").strip()
            self._pending_custom_name = custom_name

            try:
                catalog = await self._load_catalog()
            except Exception:
                catalog = []

            query_norm = _normalize_text(query)
            choices = {}
            for stop in catalog:
                name_norm = stop["name_norm"]
                id_norm = stop["id_norm"]
                if query_norm == id_norm or query_norm in name_norm:
                    label = f"{stop['name']} ({stop['id']})"
                    choices[label] = {"id": stop["id"], "name": stop["name"]}
                    if len(choices) >= 15:
                        break

            if not choices:
                errors["base"] = "invalid_stop_search"
            else:
                self._search_choices = choices
                return await self.async_step_add_stop_select()

        schema = vol.Schema(
            {
                vol.Required("search_query", default=""): str,
                vol.Optional("custom_name", default=""): str,
            }
        )
        return self.async_show_form(step_id="add_stop_search", data_schema=schema, errors=errors)

    async def async_step_add_stop_select(self, user_input=None):
        self._ensure_draft()

        if not self._search_choices:
            return await self.async_step_add_stop_search()

        options = list(self._search_choices.keys())

        if user_input is not None:
            selected = str(user_input.get("stop_choice", "") or "")
            chosen = self._search_choices.get(selected)
            if chosen is None:
                return await self.async_step_add_stop_search()

            stop_id = str(chosen.get("id") or "").strip()
            stop_name = str(chosen.get("name") or "").strip()
            name = str(self._pending_custom_name or "").strip() or stop_name

            if stop_id:
                updated = []
                replaced = False
                for stop in self._draft["extra_stops"]:
                    if str(stop.get("id", "")).strip() == stop_id:
                        updated.append({"id": stop_id, "name": name})
                        replaced = True
                    else:
                        updated.append(stop)

                if not replaced:
                    updated.append({"id": stop_id, "name": name})

                self._draft["extra_stops"] = updated

            self._search_choices = {}
            self._pending_custom_name = ""
            return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required("stop_choice", default=options[0]): vol.In(options),
            }
        )
        return self.async_show_form(step_id="add_stop_select", data_schema=schema, errors={})

    async def async_step_remove_stop(self, user_input=None):
        self._ensure_draft()

        extra_stops = self._draft.get("extra_stops", [])
        if not extra_stops:
            return await self.async_step_init()

        choices = {
            f"{stop.get('name', '')} ({stop.get('id', '')})": str(stop.get("id", ""))
            for stop in extra_stops
            if str(stop.get("id", "")).strip()
        }

        if not choices:
            return await self.async_step_init()

        labels = list(choices.keys())

        if user_input is not None:
            selected = str(user_input.get("stop_choice", "") or "")
            stop_id = choices.get(selected)
            if stop_id:
                self._draft["extra_stops"] = [
                    stop
                    for stop in extra_stops
                    if str(stop.get("id", "")).strip() != stop_id
                ]
            return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required("stop_choice", default=labels[0]): vol.In(labels),
            }
        )
        return self.async_show_form(step_id="remove_stop", data_schema=schema, errors={})

    async def async_step_finish(self, user_input=None):
        self._ensure_draft()
        return self.async_create_entry(title="", data=self._draft)
