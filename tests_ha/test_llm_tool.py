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
    return await llm.async_get_api(hass, "vigobus", context)


async def _ask(api, **args):
    result = await api.async_call_tool(llm.ToolInput(tool_name=TOOL, tool_args=args))
    return result.data["answer"]


async def test_the_tool_is_offered_to_agents(api):
    names = [tool.name for tool in api.tools]
    assert names == [TOOL]
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


async def test_any_stop_in_vigo_can_be_asked_about(api):
    # "Cruz de Maria" is not configured anywhere: it is found in the catalog.
    speech = await _ask(api, stop="cruz de maria", line="")
    assert "Cruz de María" in speech
    assert "C1" in speech


async def test_an_unknown_stop_gets_a_clear_answer(api):
    speech = await _ask(api, stop="Atlantida", line="")
    assert "Atlantida" in speech


async def test_the_result_is_one_short_final_answer(api):
    result = await api.async_call_tool(llm.ToolInput(tool_name=TOOL, tool_args={"stop": "Urzaiz"}))
    assert list(result.data) == ["answer"]
    assert "ONCE per question" in api.api_prompt


# --------------------------------------------------------------------------
# The dedicated, tiny API
# --------------------------------------------------------------------------


def _context():
    return llm.LLMContext(
        platform="ollama",
        context=Context(),
        language="es",
        assistant="conversation",
        device_id=None,
    )


async def test_a_dedicated_api_with_a_tiny_prompt_is_registered(hass, setup_entry):
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "llm", {})
    await hass.async_block_till_done()

    assert "vigobus" in [api.id for api in llm.async_get_apis(hass)]

    instance = await llm.async_get_api(hass, "vigobus", _context())
    assert [tool.name for tool in instance.tools] == [TOOL]
    # No entity list, no other tools: a few hundred tokens at most.
    assert len(instance.api_prompt) < 1200

    result = await instance.async_call_tool(llm.ToolInput(tool_name=TOOL, tool_args={"stop": "Urzaiz"}))
    assert "Urzaiz" in result.data["answer"]


async def test_the_api_can_be_combined_with_assist(hass, setup_entry):
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "llm", {})
    await hass.async_block_till_done()

    instance = await llm.async_get_api(hass, ["assist", "vigobus"], _context())
    names = [tool.name for tool in instance.tools]
    # Combined APIs namespace their tools: the bus tool is there exactly once,
    # next to Assist's own.
    assert sum(name.endswith(TOOL) for name in names) == 1
    assert any("GetLiveContext" in name for name in names)


async def test_the_api_goes_away_when_the_integration_is_unloaded(hass, setup_entry):
    assert await async_setup_component(hass, "llm", {})
    await hass.async_block_till_done()
    assert "vigobus" in [api.id for api in llm.async_get_apis(hass)]

    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert "vigobus" not in [api.id for api in llm.async_get_apis(hass)]


async def test_the_api_defines_every_field_home_assistant_reads(hass, setup_entry):
    """Regression: Home Assistant 2026.11 reads requires_admin when it combines APIs.

    The class is a slotted dataclass; skipping its constructor left the field
    unset and every combined agent failed with an AttributeError.
    """
    api = next(item for item in llm.async_get_apis(hass) if item.id == "vigobus")
    assert api.id == "vigobus"
    assert api.hass is hass
    if "requires_admin" in llm.API.__dataclass_fields__:  # added in 2026.11
        assert api.requires_admin is False


class _OtherAPI(llm.API):
    async def async_get_api_instance(self, llm_context):
        return llm.APIInstance(api=self, api_prompt="x", llm_context=llm_context, tools=[])


async def test_combining_with_any_other_api_works(hass, setup_entry):
    """The exact call that failed: Home Assistant merging several APIs."""
    llm.async_register_api(hass, _OtherAPI(hass=hass, id="other", name="Other"))

    instance = await llm.async_get_api(hass, ["other", "vigobus"], _context())

    names = [tool.name for tool in instance.tools]
    # The prefix of a combined tool depends on the Home Assistant version.
    assert len(names) == 1
    assert names[0].endswith(TOOL)


async def test_assist_alone_does_not_get_a_duplicate_tool(hass, setup_entry):
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "llm", {})
    await hass.async_block_till_done()

    instance = await llm.async_get_api(hass, llm.LLM_API_ASSIST, _context())
    assert not any(name.endswith(TOOL) for name in (tool.name for tool in instance.tools))
