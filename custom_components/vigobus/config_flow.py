import voluptuous as vol

from homeassistant import config_entries

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
    return "\n".join(lines)


def _parse_extra_stops(raw_value):
    extra_stops = []
    errors = False
    seen_ids = set()
    seen_names = set()

    raw = str(raw_value or "")
    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue

        if "," in text:
            parts = text.split(",", 1)
        elif ";" in text:
            parts = text.split(";", 1)
        else:
            parts = [text, ""]

        stop_id = parts[0].strip()
        name = parts[1].strip() or f"stop_{stop_id}"
        if not stop_id:
            errors = True
            continue

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
            extra_stops, has_invalid_lines = _parse_extra_stops(user_input.get("extra_stops", ""))
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

    async def async_step_init(self, user_input=None):
        errors = {}

        defaults = {
            "auto_nearest": self._config_entry.options.get(
                "auto_nearest",
                self._config_entry.data.get("auto_nearest", True),
            ),
            "nearest_name": self._config_entry.options.get(
                "nearest_name",
                self._config_entry.data.get("nearest_name", ""),
            ),
            "extra_stops": _serialize_extra_stops(
                self._config_entry.options.get(
                    "extra_stops",
                    self._config_entry.data.get("extra_stops", []),
                )
            ),
            "scan_interval": int(
                self._config_entry.options.get(
                    "scan_interval",
                    self._config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL),
                )
            ),
            "nearest_recalc_distance_m": int(
                self._config_entry.options.get(
                    "nearest_recalc_distance_m",
                    self._config_entry.data.get(
                        "nearest_recalc_distance_m",
                        DEFAULT_NEAREST_RECALC_DISTANCE_M,
                    ),
                )
            ),
            "notify_enabled": bool(
                self._config_entry.options.get(
                    "notify_enabled",
                    self._config_entry.data.get("notify_enabled", DEFAULT_NOTIFY_ENABLED),
                )
            ),
            "notify_minutes": int(
                self._config_entry.options.get(
                    "notify_minutes",
                    self._config_entry.data.get("notify_minutes", DEFAULT_NOTIFY_MINUTES),
                )
            ),
            "notify_cooldown_min": int(
                self._config_entry.options.get(
                    "notify_cooldown_min",
                    self._config_entry.data.get("notify_cooldown_min", DEFAULT_NOTIFY_COOLDOWN_MIN),
                )
            ),
            "alerts_lang": str(
                self._config_entry.options.get(
                    "alerts_lang",
                    self._config_entry.data.get("alerts_lang", DEFAULT_ALERTS_LANG),
                )
            ),
            "alerts_max_per_stop": int(
                self._config_entry.options.get(
                    "alerts_max_per_stop",
                    self._config_entry.data.get("alerts_max_per_stop", DEFAULT_ALERTS_MAX_PER_STOP),
                )
            ),
        }

        if user_input is not None:
            extra_stops, has_invalid_lines = _parse_extra_stops(user_input.get("extra_stops", ""))
            if has_invalid_lines:
                errors["base"] = "invalid_extra_stops"

            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        "auto_nearest": bool(user_input.get("auto_nearest", True)),
                        "nearest_name": str(user_input.get("nearest_name", "")).strip(),
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

            defaults = {
                "auto_nearest": bool(user_input.get("auto_nearest", True)),
                "nearest_name": str(user_input.get("nearest_name", "")).strip(),
                "extra_stops": str(user_input.get("extra_stops", "")),
                "scan_interval": int(user_input.get("scan_interval", DEFAULT_SCAN_INTERVAL)),
                "nearest_recalc_distance_m": int(
                    user_input.get("nearest_recalc_distance_m", DEFAULT_NEAREST_RECALC_DISTANCE_M)
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

        schema = vol.Schema(
            {
                vol.Optional("auto_nearest", default=defaults["auto_nearest"]): bool,
                vol.Optional("nearest_name", default=defaults["nearest_name"]): str,
                vol.Optional("scan_interval", default=defaults["scan_interval"]): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Optional(
                    "nearest_recalc_distance_m",
                    default=defaults["nearest_recalc_distance_m"],
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_NEAREST_RECALC_DISTANCE_M,
                        max=MAX_NEAREST_RECALC_DISTANCE_M,
                    ),
                ),
                vol.Optional("notify_enabled", default=defaults["notify_enabled"]): bool,
                vol.Optional("notify_minutes", default=defaults["notify_minutes"]): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_NOTIFY_MINUTES, max=MAX_NOTIFY_MINUTES),
                ),
                vol.Optional(
                    "notify_cooldown_min",
                    default=defaults["notify_cooldown_min"],
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_NOTIFY_COOLDOWN_MIN, max=MAX_NOTIFY_COOLDOWN_MIN),
                ),
                vol.Optional("alerts_lang", default=defaults["alerts_lang"]): vol.In(
                    ["es", "en", "gl"]
                ),
                vol.Optional(
                    "alerts_max_per_stop",
                    default=defaults["alerts_max_per_stop"],
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_ALERTS_MAX_PER_STOP, max=MAX_ALERTS_MAX_PER_STOP),
                ),
                vol.Optional("extra_stops", default=defaults["extra_stops"]): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
