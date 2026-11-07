import shutil
from pathlib import Path

import pytest
import yaml
from homeassistant.components.blueprint import models
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.vigobus.const import DOMAIN, SIGNAL_NEW_ALERTS

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINTS = sorted((ROOT / "blueprints" / "automation" / "vigobus").glob("*.yaml"))


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_blueprint_is_valid(path):
    blueprint = models.Blueprint(
        load_yaml_dict(str(path)), expected_domain="automation", schema=BLUEPRINT_SCHEMA
    )
    assert blueprint.metadata["source_url"].endswith(path.name)


def test_there_are_four_blueprints():
    assert len(BLUEPRINTS) == 4


def _install_blueprint(hass: HomeAssistant, name):
    target = Path(hass.config.path("blueprints/automation/vigobus"))
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "blueprints" / "automation" / "vigobus" / name, target / name)


def _entity(hass, platform, suffix, entry):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, DOMAIN, f"vigobus_{entry.entry_id}_{suffix}")
    assert entity_id
    return entity_id


async def test_arriving_blueprint_runs_the_actions(hass, setup_entry, buses):
    from .conftest import make_buses

    _install_blueprint(hass, "bus_arriving_notify.yaml")
    sensor = _entity(hass, "binary_sensor", "nearest_llegando", setup_entry)
    calls = async_mock_service(hass, "test", "arrived")

    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": "vigobus/bus_arriving_notify.yaml",
                    "input": {
                        "arriving_sensor": sensor,
                        "actions": [
                            {
                                "action": "test.arrived",
                                "data": {"line": "{{ line }}", "minutes": "{{ minutes }}"},
                            }
                        ],
                    },
                }
            }
        },
    )

    # The sensor starts on (next bus in 3 min). Make it go off, then on again.
    buses["value"] = make_buses(("C1", 20, 900))
    await hass.data[DOMAIN][setup_entry.entry_id].async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "off"

    buses["value"] = make_buses(("18A", 2, 50))
    await hass.data[DOMAIN][setup_entry.entry_id].async_refresh()
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["line"] == "18A"
    assert str(calls[0].data["minutes"]) == "2"


async def test_new_alert_blueprint_filters_by_line(hass, setup_entry):
    _install_blueprint(hass, "new_alert_notify.yaml")
    event = _entity(hass, "event", "avisos_evento", setup_entry)
    calls = async_mock_service(hass, "test", "alert")

    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": "vigobus/new_alert_notify.yaml",
                    "input": {
                        "alert_event": event,
                        "only_lines": "C1, 18A",
                        "actions": [
                            {
                                "action": "test.alert",
                                "data": {"title": "{{ title }}", "lines": "{{ lines }}"},
                            }
                        ],
                    },
                }
            }
        },
    )

    signal = SIGNAL_NEW_ALERTS.format(setup_entry.entry_id)
    async_dispatcher_send(hass, signal, [{"title": "Other line", "lineas": "9", "inicio": 1, "fin": 2}])
    await hass.async_block_till_done()
    assert len(calls) == 0

    async_dispatcher_send(hass, signal, [{"title": "Desvio C1", "lineas": "C1, 5", "inicio": 1, "fin": 2}])
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data["title"] == "Desvio C1"


# --------------------------------------------------------------------------
# Assist sentences
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "text", "stop"),
    [
        ("es", "cuándo pasa el bus", None),
        ("es", "cuándo pasa el autobús por Urzaiz", "Urzaiz"),
        ("es", "a qué hora llega el próximo bus a la parada Gran Vía", "Gran Vía"),
        ("gl", "cando pasa o bus", None),
        ("gl", "cando chega o autobús en Urzaiz", "Urzaiz"),
        ("en", "when does the bus come", None),
        ("en", "when does the next bus arrive at Urzaiz", "Urzaiz"),
    ],
)
def test_sentences_trigger_the_intent(language, text, stop):
    from hassil import Intents, recognize

    data = yaml.safe_load((ROOT / "custom_sentences" / language / "vigobus.yaml").read_text(encoding="utf-8"))
    intents = Intents.from_dict(data)
    result = recognize(text, intents)
    assert result is not None, text
    assert result.intent.name == "VigoBusNextBus"
    if stop is None:
        assert "stop" not in result.entities
    else:
        assert result.entities["stop"].value.strip().lower() == stop.lower()
