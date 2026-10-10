"""Stateless chat turn → stream of neutral events (text / usage / error / done).

Phase 1 is plain chat (no tools). The caller resolves the runtime config (which enforces the
enable switch) *before* streaming starts, so this generator never touches the database.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from services.ai_assistant.exceptions import AiAssistantError
from services.ai_assistant.prompts import BASE_SYSTEM_PROMPT, CONNECTION_TEST_PROMPT
from services.ai_assistant.providers.base import ChatMessage, LlmProvider, ProviderError
from services.ai_assistant.providers.registry import build_provider
from services.ai_assistant.settings_service import AiRuntimeConfig

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 16000
TEST_MAX_OUTPUT_TOKENS = 64

ProviderFactory = Callable[..., LlmProvider]


@dataclass(frozen=True)
class ChatEvent:
    """``event`` is the SSE event name; ``data`` its JSON payload."""

    event: str
    data: dict[str, Any]


async def stream_chat(
    config: AiRuntimeConfig,
    messages: list[ChatMessage],
    *,
    provider_factory: ProviderFactory = build_provider,
) -> AsyncIterator[ChatEvent]:
    try:
        provider = provider_factory(
            config.provider, api_key=config.api_key, base_url=config.base_url
        )
        async for item in provider.stream(
            model=config.model,
            system=BASE_SYSTEM_PROMPT,
            messages=messages,
            max_tokens=MAX_OUTPUT_TOKENS,
        ):
            if item.type == "text":
                yield ChatEvent("text", {"text": item.text})
            else:
                yield ChatEvent(
                    "usage",
                    {"input_tokens": item.input_tokens, "output_tokens": item.output_tokens},
                )
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
