"""Anthropic adapter (official SDK). Maps SDK errors to provider-neutral ``ProviderError``s."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic

from services.ai_assistant.providers.base import (
    ChatMessage,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderRequestError,
    ProviderUnavailableError,
    StreamEvent,
    ToolCall,
    ToolSpec,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 120.0


def map_anthropic_error(exc: Exception) -> ProviderError:
    """Translate an SDK exception; the raw API body is deliberately never echoed."""
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ProviderAuthError("The provider rejected the API key")
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderRateLimitError("The provider rate limit or quota was reached")
    if isinstance(exc, anthropic.NotFoundError):
        return ProviderRequestError("Model not found or not available for this API key")
    if isinstance(exc, anthropic.APITimeoutError | anthropic.APIConnectionError):
        return ProviderUnavailableError("Could not reach the provider")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500 or exc.status_code == 529:
            return ProviderUnavailableError("The provider is temporarily unavailable")
        return ProviderRequestError("The provider rejected the request")
    return ProviderUnavailableError("The provider request failed")


def _to_api_message(message: ChatMessage) -> dict[str, Any]:
    if message.role == "assistant" and message.raw is not None:
        # Echo the provider's own blocks (incl. thinking) unchanged when continuing a tool turn.
        return {"role": "assistant", "content": message.raw}
    if message.tool_results:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": result.tool_use_id,
                    "content": result.content,
                    "is_error": result.is_error,
                }
                for result in message.tool_results
            ],
        }
    return {"role": message.role, "content": message.content}


def _to_api_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }


class AnthropicProvider:
    def __init__(self, api_key: str) -> None:
        # max_retries: the SDK retries 429/5xx with backoff; keep its default.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)

    async def aclose(self) -> None:
        await self._client.close()

    async def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[ChatMessage],
        max_tokens: int,
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[StreamEvent]:
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [_to_api_message(m) for m in messages],
        }
        if tools:
            request["tools"] = [_to_api_tool(t) for t in tools]
        try:
            async with self._client.messages.stream(**request) as stream:
                async for text in stream.text_stream:
                    yield StreamEvent(type="text", text=text)
                final = await stream.get_final_message()
        except ProviderError:
            raise
        except anthropic.AnthropicError as exc:
            logger.warning("Anthropic request failed: %s", type(exc).__name__)
            raise map_anthropic_error(exc) from exc

        if final.stop_reason == "refusal":
            raise ProviderRefusalError("The provider declined to answer this request")
        tool_calls = tuple(
            ToolCall(id=block.id, name=block.name, input=dict(block.input))
            for block in final.content
            if block.type == "tool_use"
        )
        yield StreamEvent(
            type="turn",
            tool_calls=tool_calls,
            stop_reason=final.stop_reason or "",
            raw=final.content,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
        )
