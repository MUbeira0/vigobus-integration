"""Tests that run against a real Home Assistant (pytest-homeassistant-custom-component).

They live apart from ``tests/`` because that suite replaces ``homeassistant``
with lightweight stubs, which cannot coexist with the real package.
"""

import sys
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

pytest_plugins = "pytest_homeassistant_custom_component"

if sys.platform == "win32":
    # asyncio's Windows event loop builds its self-pipe from a TCP socketpair,
    # which the plugin's socket guard would block. Linux (CI) is unaffected.
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None

HOME = (42.2328, -8.7226)
NEAR_STOP = {"id": "1", "stop_id": "1", "latitud": 42.2340, "longitud": -8.7226}

CATALOG = [
    {
        "id": "1234",
        "name": "Urzaiz",
        "id_norm": "1234",
        "name_norm": "urzaiz",
        "id_aliases": ["1234"],
        "id_aliases_norm": ["1234"],
        "stop_id": None,
        "lat": 42.2,
        "lon": -8.7,
    }
]


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations, socket_enabled):
    yield


def make_buses(*pairs):
    return {
        "estimaciones": [
            {"linea": linea, "ruta": "CENTRO", "minutos": minutos, "metros": metros}
            for linea, minutos, metros in pairs
        ]
    }


@pytest.fixture
def buses():
    """The estimaciones every stop returns; tests may replace the list."""
    return {"value": make_buses(("C1", 3, 100), ("C1", 10, -1))}


@pytest.fixture
def entry_data():
    return {
        "auto_nearest": True,
        "nearest_name": "Casa",
        "extra_stops": [{"id": "1234", "name": "Urzaiz", "line": ""}],
        "notify_enabled": False,
    }


@pytest.fixture
async def setup_entry(hass, buses, entry_data):
    """Set the integration up with the Vigo network calls mocked."""
    hass.states.async_set("zone.home", "0", {"latitude": HOME[0], "longitude": HOME[1]})

    entry = MockConfigEntry(domain="vigobus", data=entry_data, options={})
    entry.add_to_hass(hass)

    async def _estimacion(_self, _stop_id):
        return buses["value"]

    with (
        patch("custom_components.vigobus.api.VigoBusApi.get_estimacion", _estimacion),
        patch(
            "custom_components.vigobus.api.VigoBusApi.get_nearest_stop",
            AsyncMock(return_value=NEAR_STOP),
        ),
        patch(
            "custom_components.vigobus.api.VigoBusApi.get_line_alerts",
            AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.vigobus.api.VigoBusApi.get_line_colors",
            AsyncMock(return_value={"C1": "#ff0000"}),
        ),
        patch(
            "custom_components.vigobus.stop_catalog._get_catalog_stops",
            AsyncMock(return_value=CATALOG),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry
