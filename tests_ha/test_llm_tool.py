import pytest
from homeassistant.core import Context
from homeassistant.helpers import llm
from homeassistant.setup import async_setup_component

TOOL = "vigobus__VigoBusNextBus"


@pytest.fixture
async def api(hass, setup_entry):
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "llm", {})
    await hass.async_block_till_done()
    context = llm.LLMContext(
        platform="ollama",
        context=Context(),
        language="es",
        assistant="conversation",
        device_id=None,
    )
    return await llm.async_get_api(hass, llm.LLM_API_ASSIST, context)


async def _ask(api, **args):
    result = await api.async_call_tool(llm.ToolInput(tool_name=TOOL, tool_args=args))
    return result.data["speech"]["plain"]["speech"]


async def test_the_tool_is_offered_to_agents(api):
    names = [tool.name for tool in api.tools]
    assert TOOL in names
    assert "VigoBus" in api.api_prompt


async def test_the_tool_answers_a_named_stop(api):
    speech = await _ask(api, stop="Urzaiz", line="")
    assert "Urzaiz" in speech
    assert "C1" in speech


async def test_a_line_put_in_the_stop_slot_is_understood(api):
    # Small models often swap the slots: the stop name ends up in "line".
    speech = await _ask(api, stop="", line="Urzaiz")
    assert "Urzaiz" in speech


async def test_line_and_home_packed_in_one_slot(api):
    # "25 por casa" in the stop slot means line 25 at the home stop.
    speech = await _ask(api, stop="25 por casa")
    assert "Casa" in speech
    assert "25" in speech
