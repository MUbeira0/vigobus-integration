"""Expose the "when does the bus come?" question to AI conversation agents.

Since Home Assistant 2026.x, the Assist API only offers an agent the tools that
integrations declare in an ``llm`` platform; a registered intent on its own is
invisible to it. This file declares that tool.

The tool is deliberately simple. It returns one short sentence, so a small
model reads the answer, repeats it and stops instead of calling the tool again.
"""

from collections.abc import Callable

import probatio
from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.llm import (
    API,
    LLM_API_ASSIST,
    APIInstance,
    LLMContext,
    Tool,
    ToolAnnotations,
    ToolInput,
    ToolResult,
    async_register_api,
    selector_serializer,
)

from .const import DOMAIN
from .voice import INTENT_NEXT_BUS, async_answer

TOOL_NAME = f"{DOMAIN}__{INTENT_NEXT_BUS}"

PROMPT = (
    "VigoBus (buses of Vigo): to answer when a bus arrives, call the "
    f"{TOOL_NAME} tool ONCE per question. Put in 'stop' only the stop name the user said; "
    "leave it empty for the user's home or when no stop is said. Put in 'line' only a bus "
    "line the user said (for example 25, C1 or 18A), otherwise leave it empty. The tool "
    "returns the final answer: say it to the user in one short sentence and do not call "
    "the tool again. Never invent stops, lines or times."
)


class NextBusTool(Tool):
    """Tells when the next bus arrives at a stop (any stop in Vigo)."""

    name = TOOL_NAME
    title = "Next VigoBus bus"
    integration = DOMAIN
    description = (
        "Tells when the next bus arrives at a stop in Vigo. Call it once per question; "
        "it returns the final answer to give to the user."
    )
    # Reads public bus data only and never changes anything.
    annotations = ToolAnnotations(read_only=True, destructive=False, idempotent=True, open_world=True)
    parameters = probatio.Schema(
        {
            probatio.Optional(
                "stop",
                description="Name of the bus stop the user said. Leave empty for the user's home stop.",
            ): str,
            probatio.Optional(
                "line",
                description="Bus line code the user said, for example 25, C1 or 18A. Leave empty if none.",
            ): str,
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: LLMContext
    ) -> ToolResult:
        args = tool_input.tool_args or {}
        answer = await async_answer(hass, args.get("stop"), args.get("line"), llm_context.language)
        return ToolResult(data={"answer": answer})


@callback
def async_get_tools(hass: HomeAssistant, llm_context: LLMContext, api_id: str) -> LLMTools | None:
    """Return the VigoBus tool for the Assist API while the integration is loaded."""
    if api_id != LLM_API_ASSIST:
        return None

    if not hass.data.get(DOMAIN):
        return None

    return LLMTools(tools=[NextBusTool()], prompt=PROMPT)


# ---------------------------------------------------------------------------
# A small API of its own
# ---------------------------------------------------------------------------

API_ID = DOMAIN


class VigoBusAPI(API):
    """An LLM API with only the bus tool and a tiny prompt.

    The Assist API sends the model every exposed entity, which can be thousands
    of tokens: more than a small local model can hold, so it loses the
    instructions and the tool answer and loops. Giving an agent just this API
    keeps the prompt to a couple of hundred tokens.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.id = API_ID
        self.name = "VigoBus (solo autobuses)"

    async def async_get_api_instance(self, llm_context: LLMContext) -> APIInstance:
        return APIInstance(
            api=self,
            api_prompt=PROMPT,
            llm_context=llm_context,
            tools=[NextBusTool()],
            custom_serializer=selector_serializer,
        )


@callback
def async_register_llm_api(hass: HomeAssistant) -> Callable[[], None]:
    """Register the VigoBus API; returns the function that unregisters it."""
    return async_register_api(hass, VigoBusAPI(hass))
