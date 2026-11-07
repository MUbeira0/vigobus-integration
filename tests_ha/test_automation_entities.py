from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent as intent_helper
from homeassistant.helpers.dispatcher import async_dispatcher_send

from custom_components.vigobus.const import DOMAIN, SIGNAL_NEW_ALERTS

from .conftest import make_buses


def _state(hass, entry, platform, unique_suffix):
    registry = er.async_get(hass)
    unique_id = f"vigobus_{entry.entry_id}_{unique_suffix}"
    entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id, f"{platform} {unique_id} was not created"
    return hass.states.get(entity_id)


async def test_arriving_binary_sensor_turns_on_when_bus_is_close(hass, setup_entry):
    state = _state(hass, setup_entry, "binary_sensor", "nearest_llegando")
    assert state.state == "on"  # next bus in 3 min, default threshold 5
    assert state.attributes["minutes"] == 3
    assert state.attributes["line"] == "C1"


async def test_arriving_binary_sensor_is_off_when_bus_is_far(hass, setup_entry, buses):
    buses["value"] = make_buses(("C1", 12, 900))
    coordinator = hass.data[DOMAIN][setup_entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = _state(hass, setup_entry, "binary_sensor", "nearest_llegando")
    assert state.state == "off"


async def test_leave_in_sensor_uses_walk_time(hass, setup_entry):
    # ~133 m to the stop -> 3 min walk + 1 min buffer = 4 min needed.
    # The 3 min bus is too close, the 10 min one is catchable: leave in 6.
    state = _state(hass, setup_entry, "sensor", "nearest_salir_en")
    assert state.state == "6"
    assert state.attributes["walk_min"] == 3
    assert state.attributes["bus_minutes"] == 10
    assert state.attributes["missed_minutes"] == 3

    leave_now = _state(hass, setup_entry, "binary_sensor", "nearest_salir_ya")
    assert leave_now.state == "off"


async def test_leave_now_turns_on_when_it_is_time(hass, setup_entry, buses):
    buses["value"] = make_buses(("C1", 4, 100))
    coordinator = hass.data[DOMAIN][setup_entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    leave_now = _state(hass, setup_entry, "binary_sensor", "nearest_salir_ya")
    assert leave_now.state == "on"


async def test_service_status_and_reliability_sensors(hass, setup_entry):
    status = _state(hass, setup_entry, "sensor", "estado_servicio")
    assert status.state == "ok"

    registry = er.async_get(hass)
    reliability_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"vigobus_{setup_entry.entry_id}_nearest_fiabilidad"
    )
    assert reliability_id is not None
    # Disabled by default, so it must exist in the registry only.
    assert registry.async_get(reliability_id).disabled


async def test_new_alert_fires_event_entity(hass, setup_entry):
    registry = er.async_get(hass)
    event_id = registry.async_get_entity_id(
        "event", DOMAIN, f"vigobus_{setup_entry.entry_id}_avisos_evento"
    )
    assert event_id

    async_dispatcher_send(
        hass,
        SIGNAL_NEW_ALERTS.format(setup_entry.entry_id),
        [{"title": "Desvio linea C1", "lineas": "C1", "inicio": "a", "fin": "b"}],
    )
    await hass.async_block_till_done()

    state = hass.states.get(event_id)
    assert state.attributes["event_type"] == "new_alert"
    assert state.attributes["title"] == "Desvio linea C1"
    assert state.attributes["lines"] == "C1"


async def test_assist_intent_answers_next_bus(hass, setup_entry):
    response = await intent_helper.async_handle(
        hass, "test", "VigoBusNextBus", {"stop": {"value": "Urzaiz"}}, language="es"
    )
    speech = response.speech["plain"]["speech"]
    assert "Urzaiz" in speech
    assert "C1" in speech
    assert "3 minutos" in speech


async def test_assist_intent_without_stop_uses_home_stop(hass, setup_entry):
    response = await intent_helper.async_handle(hass, "test", "VigoBusNextBus", {}, language="en")
    assert "Casa" in response.speech["plain"]["speech"]


async def test_assist_intent_unknown_stop(hass, setup_entry):
    response = await intent_helper.async_handle(
        hass, "test", "VigoBusNextBus", {"stop": {"value": "Atlantida"}}, language="es"
    )
    assert "Atlantida" in response.speech["plain"]["speech"]
