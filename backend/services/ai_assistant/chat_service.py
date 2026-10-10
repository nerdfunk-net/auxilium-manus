"""Stateless chat turn → stream of neutral events (text / tool / proposal / usage / error / done).

The caller resolves the runtime config (which enforces the enable switch) and builds the
toolbox *before* streaming starts. This generator never holds a database session; tools open
short-lived ones of their own.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from services.ai_assistant.agent_loop import run_agent
from services.ai_assistant.events import ChatEvent
from services.ai_assistant.exceptions import AiAssistantError
from services.ai_assistant.prompts import BASE_SYSTEM_PROMPT, CONNECTION_TEST_PROMPT
from services.ai_assistant.providers.base import ChatMessage, LlmProvider, ProviderError
from services.ai_assistant.providers.registry import build_provider
from services.ai_assistant.settings_service import AiRuntimeConfig
from services.ai_assistant.tools.base import Toolbox

logger = logging.getLogger(__name__)

TEST_MAX_OUTPUT_TOKENS = 64

ProviderFactory = Callable[..., LlmProvider]


__all__ = ["ChatEvent", "check_connection", "stream_chat"]


async def stream_chat(
    config: AiRuntimeConfig,
    messages: list[ChatMessage],
    *,
    provider_factory: ProviderFactory = build_provider,
    toolbox: Toolbox | None = None,
    system: str = BASE_SYSTEM_PROMPT,
) -> AsyncIterator[ChatEvent]:
    try:
        provider = provider_factory(
            config.provider, api_key=config.api_key, base_url=config.base_url
        )
        async for event in run_agent(
            provider=provider,
            model=config.model,
            system=system,
            messages=messages,
            toolbox=toolbox,
        ):
            yield event
    except ProviderError as exc:
        yield ChatEvent("error", {"code": exc.code, "message": exc.message})
    except AiAssistantError as exc:
        yield ChatEvent("error", {"code": exc.code, "message": str(exc)})
    except Exception:
        # Never leak internals to the client; the stack goes to the server log only.
        logger.exception("Unexpected error in AI assistant chat stream")
        yield ChatEvent(
            "error",
            {"code": "internal_error", "message": "The assistant failed unexpectedly"},
        )
    yield ChatEvent("done", {})


async def check_connection(
    config: AiRuntimeConfig, *, provider_factory: ProviderFactory = build_provider
) -> dict[str, Any]:
    """Cheap request proving the key + model work. Returns ``{ok, code?, message?}``."""
    try:
        provider = provider_factory(
            config.provider, api_key=config.api_key, base_url=config.base_url
        )
        async for _ in provider.stream(
            model=config.model,
            system=BASE_SYSTEM_PROMPT,
            messages=[ChatMessage(role="user", content=CONNECTION_TEST_PROMPT)],
            max_tokens=TEST_MAX_OUTPUT_TOKENS,
        ):
            pass
    except ProviderError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    except AiAssistantError as exc:
        return {"ok": False, "code": exc.code, "message": str(exc)}
    except Exception:
        logger.exception("Unexpected error testing AI assistant connection")
        return {"ok": False, "code": "internal_error", "message": "The connection test failed"}
    return {"ok": True}
