from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.repairs.issue_handler import RepairsFlowManager
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from custom_components.vigobus.const import DOMAIN

PLAN = {
    "itineraries": [
        {
            "depart": "08:12",
            "arrive": "08:40",
            "duration_min": 28,
            "transfers": 0,
            "lines": ["C1"],
            "legs": [],
        }
    ]
}


# --------------------------------------------------------------------------
# Commute profiles
# --------------------------------------------------------------------------


@pytest.fixture
async def _monday_morning(hass, freezer):
    await hass.config.async_set_time_zone("Europe/Madrid")
    freezer.move_to("2026-11-09 07:00:00+00:00")  # Monday 08:00 in Madrid


@pytest.fixture
def entry_data(_monday_morning):
    return {
        "auto_nearest": True,
        "nearest_name": "Casa",
        "extra_stops": [],
        "notify_enabled": False,
        "commutes": [
            {
                "name": "Trabajo",
                "origin": "home",
                "destination_stop_id": "1234",
                "destination_name": "Urzaiz",
                "days": ["mon", "tue", "wed", "thu", "fri"],
                "time": "08:15",
                "lead_min": 20,
            }
        ],
    }


@pytest.mark.usefixtures("_monday_morning")
async def test_commute_sensor_gets_the_best_itinerary(hass, buses, entry_data):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from .conftest import CATALOG, NEAR_STOP

    hass.states.async_set("zone.home", "0", {"latitude": 42.2328, "longitude": -8.7226})
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data, options={})
    entry.add_to_hass(hass)

    plan = AsyncMock(return_value=PLAN)

    async def _estimacion(_self, _stop_id):
        return buses["value"]

    with (
        patch("custom_components.vigobus.api.VigoBusApi.get_estimacion", _estimacion),
        patch(
            "custom_components.vigobus.api.VigoBusApi.get_nearest_stop",
            AsyncMock(return_value=NEAR_STOP),
        ),
        patch("custom_components.vigobus.api.VigoBusApi.get_line_alerts", AsyncMock(return_value={})),
        patch("custom_components.vigobus.api.VigoBusApi.get_line_colors", AsyncMock(return_value={})),
        patch(
            "custom_components.vigobus.stop_catalog._get_catalog_stops",
            AsyncMock(return_value=CATALOG),
        ),
        patch("custom_components.vigobus.plan_trip_handler", plan),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"vigobus_{entry.entry_id}_trayecto_trabajo"
        )
        assert entity_id
        state = hass.states.get(entity_id)
        assert state.state == "08:12"
        assert state.attributes["arrive"] == "08:40"
        assert state.attributes["lines"] == ["C1"]
        assert "Trabajo" in state.attributes["summary"]

        # It is planned once per day: a second scan must not plan again.
        plan.assert_awaited_once()
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        plan.assert_awaited_once()


# --------------------------------------------------------------------------
# Repairs
# --------------------------------------------------------------------------


@pytest.fixture
def stale_entry_data():
    return {
        "auto_nearest": False,
        "extra_stops": [
            {"id": "1234", "name": "Urzaiz", "line": ""},
            {"id": "9999", "name": "Fantasma", "line": ""},
        ],
    }


async def _setup_with(hass, buses, data):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from .conftest import CATALOG

    hass.states.async_set("zone.home", "0", {"latitude": 42.2328, "longitude": -8.7226})
    entry = MockConfigEntry(domain=DOMAIN, data=data, options={})
    entry.add_to_hass(hass)

    async def _estimacion(_self, _stop_id):
        return buses["value"]

    patches = [
        patch("custom_components.vigobus.api.VigoBusApi.get_estimacion", _estimacion),
        patch("custom_components.vigobus.api.VigoBusApi.get_line_alerts", AsyncMock(return_value={})),
        patch("custom_components.vigobus.api.VigoBusApi.get_line_colors", AsyncMock(return_value={})),
        patch(
            "custom_components.vigobus.stop_catalog._get_catalog_stops",
            AsyncMock(return_value=CATALOG),
        ),
    ]
    for item in patches:
        item.start()
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    except BaseException:
        for item in patches:
            item.stop()
        raise
    return entry, patches


async def test_repair_flow_removes_missing_stop(hass, buses, stale_entry_data):
    entry, patches = await _setup_with(hass, buses, stale_entry_data)
    try:
        issue_id = f"stop_missing_{entry.entry_id}_9999"
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None and issue.is_fixable
        # The stop that still exists must not be flagged.
        assert ir.async_get(hass).async_get_issue(DOMAIN, f"stop_missing_{entry.entry_id}_1234") is None

        assert await async_setup_component(hass, "repairs", {})
        manager = RepairsFlowManager(hass)
        result = await manager.async_init(DOMAIN, data={"issue_id": issue_id})
        result = await manager.async_configure(result["flow_id"], {})
        assert result["type"] == "create_entry"

        await hass.async_block_till_done()
        remaining = [stop["id"] for stop in entry.options["extra_stops"]]
        assert remaining == ["1234"]
    finally:
        for item in patches:
            item.stop()


# --------------------------------------------------------------------------
# Reconfigure + options flows
# --------------------------------------------------------------------------


async def test_reconfigure_flow_updates_the_entry(hass, setup_entry):
    result = await setup_entry.start_reconfigure_flow(hass)
    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "auto_nearest": True,
            "nearest_name": "Casa nueva",
            "nearest_line_filter": "C1",
            "nearest_devices": [],
            "auto_nearest_devices": False,
            "scan_interval": 45,
        },
    )
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert setup_entry.data["nearest_name"] == "Casa nueva"
    assert setup_entry.data["scan_interval"] == 45
    # Everything not asked about (here: the commute profiles) is kept.
    assert setup_entry.data["commutes"][0]["name"] == "Trabajo"


async def test_options_flow_adds_and_removes_a_commute(hass, setup_entry):
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    assert "add_commute" in result["menu_options"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_commute"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "name": "Trabajo",
            "origin": "home",
            "destination_query": "urzaiz",
            "days": ["mon", "tue"],
            "time": "08:15",
            "lead_min": 20,
        },
    )
    assert result["step_id"] == "add_commute_select"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"stop_choice": "Urzaiz (1234)"}
    )
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result["type"] == "create_entry"
    commute = result["data"]["commutes"][0]
    assert commute["name"] == "Trabajo"
    assert commute["destination_stop_id"] == "1234"
    assert commute["days"] == ["mon", "tue"]
    assert commute["time"] == "08:15"
