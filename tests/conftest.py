"""Shared Home Assistant stubs so custom_components.vigobus can be imported
and unit-tested without a real Home Assistant installation.

Runs once, before pytest collects any test module in this directory.
"""

import sys
import types


def _register(name, module):
    sys.modules[name] = module
    return module


def install_stubs():
    if "voluptuous" not in sys.modules:
        vol = types.ModuleType("voluptuous")
        vol.Optional = lambda *args, **kwargs: None
        vol.Required = lambda *args, **kwargs: None
        vol.All = lambda *args, **kwargs: None
        vol.Coerce = lambda *args, **kwargs: None
        vol.Range = lambda *args, **kwargs: None
        vol.In = lambda *args, **kwargs: None
        vol.Schema = lambda *args, **kwargs: None
        sys.modules["voluptuous"] = vol

    if "aiohttp" not in sys.modules:
        try:
            import aiohttp  # noqa: F401  (use the real package if it's installed)
        except ImportError:
            aiohttp = types.ModuleType("aiohttp")

            class ClientSession:
                pass

            class ClientError(Exception):
                pass

            aiohttp.ClientSession = ClientSession
            aiohttp.ClientError = ClientError
            _register("aiohttp", aiohttp)

    if "homeassistant" not in sys.modules:
        ha = _register("homeassistant", types.ModuleType("homeassistant"))

        # homeassistant.config_entries
        config_entries = types.ModuleType("homeassistant.config_entries")

        class ConfigFlow:
            def __init_subclass__(cls, **kwargs):
                # HA passes domain=... when subclassing ConfigFlow.
                return None

        class OptionsFlow:
            def __init__(self, *args, **kwargs):
                self.hass = None

        class ConfigEntry:
            pass

        config_entries.ConfigFlow = ConfigFlow
        config_entries.OptionsFlow = OptionsFlow
        config_entries.ConfigEntry = ConfigEntry
        ha.config_entries = _register("homeassistant.config_entries", config_entries)

        # homeassistant.core
        core = types.ModuleType("homeassistant.core")

        class HomeAssistant:
            pass

        class SupportsResponse:
            ONLY = "only"

        core.HomeAssistant = HomeAssistant
        core.SupportsResponse = SupportsResponse
        ha.core = _register("homeassistant.core", core)

        # homeassistant.helpers (+ submodules)
        helpers = _register("homeassistant.helpers", types.ModuleType("homeassistant.helpers"))
        ha.helpers = helpers

        aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
        aiohttp_client.async_get_clientsession = lambda _hass: object()
        helpers.aiohttp_client = _register(
            "homeassistant.helpers.aiohttp_client", aiohttp_client
        )

        selector_mod = types.ModuleType("homeassistant.helpers.selector")
        selector_mod.selector = lambda config: config
        helpers.selector = _register("homeassistant.helpers.selector", selector_mod)

        update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

        class DataUpdateCoordinator:
            def __init__(self, *args, **kwargs):
                pass

        class CoordinatorEntity:
            def __init__(self, coordinator, *args, **kwargs):
                self.coordinator = coordinator

        update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
        update_coordinator.CoordinatorEntity = CoordinatorEntity
        helpers.update_coordinator = _register(
            "homeassistant.helpers.update_coordinator", update_coordinator
        )

        device_registry = types.ModuleType("homeassistant.helpers.device_registry")

        class DeviceEntryType:
            SERVICE = "service"

        class DeviceInfo(dict):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)

        device_registry.DeviceEntryType = DeviceEntryType
        device_registry.DeviceInfo = DeviceInfo
        helpers.device_registry = _register(
            "homeassistant.helpers.device_registry", device_registry
        )

        # homeassistant.components (+ sensor, persistent_notification)
        components = _register(
            "homeassistant.components", types.ModuleType("homeassistant.components")
        )
        ha.components = components
        persistent_notification = types.ModuleType(
            "homeassistant.components.persistent_notification"
        )
        persistent_notification.async_create = lambda *args, **kwargs: None
        components.persistent_notification = _register(
            "homeassistant.components.persistent_notification", persistent_notification
        )

        sensor_mod = types.ModuleType("homeassistant.components.sensor")

        class SensorEntity:
            pass

        sensor_mod.SensorEntity = SensorEntity
        components.sensor = _register("homeassistant.components.sensor", sensor_mod)

        # homeassistant.util (+ util.dt) and slugify
        util = _register("homeassistant.util", types.ModuleType("homeassistant.util"))
        ha.util = util

        def _slugify(value, *_a, **_k):
            text = str(value or "").strip().lower()
            out = []
            prev_us = False
            for ch in text:
                if ch.isalnum():
                    out.append(ch)
                    prev_us = False
                elif not prev_us:
                    out.append("_")
                    prev_us = True
            return "".join(out).strip("_")

        util.slugify = _slugify

        dt_mod = types.ModuleType("homeassistant.util.dt")
        import datetime as _datetime

        dt_mod.utcnow = lambda: _datetime.datetime.now(_datetime.timezone.utc)
        util.dt = _register("homeassistant.util.dt", dt_mod)


install_stubs()
