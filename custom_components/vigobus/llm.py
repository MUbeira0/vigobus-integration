"""Expose the VigoBus voice intent to AI conversation agents (Ollama, OpenAI...).

Since Home Assistant 2026.x, the Assist API only offers an agent the tools that
integrations declare in an ``llm`` platform; a registered intent on its own is
invisible to it. This file declares the "when does the bus come?" tool.
"""

from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import intent
from homeassistant.helpers.llm import (
    LLM_API_ASSIST,
    IntentTool,
    LLMContext,
    ToolAnnotations,
)

from .const import DOMAIN
from .voice import INTENT_NEXT_BUS

# Reads public bus data only and never changes anything.
_ANNOTATIONS = ToolAnnotations(read_only=True, destructive=False, idempotent=True, open_world=True)

PROMPT = (
    "VigoBus (buses of Vigo): to answer when a bus arrives, call the "
    f"{DOMAIN}__{INTENT_NEXT_BUS} tool. Put in 'stop' only the stop name the user said; "
    "leave it empty for the user's home or when no stop is said. Put in 'line' only a bus "
    "line the user said (for example 25, C1 or 18A), otherwise leave it empty. Never invent "
    "stops, lines or times: use the tool's answer."
)


@callback
def async_get_tools(hass: HomeAssistant, llm_context: LLMContext, api_id: str) -> LLMTools | None:
    """Return the VigoBus tool for the Assist API while the integration is loaded."""
    if api_id != LLM_API_ASSIST:
        return None

    if not hass.data.get(DOMAIN):
        return None

    handler = next(
        (item for item in intent.async_get(hass) if item.intent_type == INTENT_NEXT_BUS),
        None,
    )
    if handler is None:
        return None

    tool = IntentTool(
        f"{DOMAIN}__{INTENT_NEXT_BUS}",
        handler,
        title="Next VigoBus bus",
        integration=DOMAIN,
        annotations=_ANNOTATIONS,
    )
    return LLMTools(tools=[tool], prompt=PROMPT)
