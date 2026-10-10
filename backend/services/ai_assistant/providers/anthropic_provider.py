"""Anthropic adapter (official SDK). Maps SDK errors to provider-neutral ``ProviderError``s."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

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


class AnthropicProvider:
    def __init__(self, api_key: str) -> None:
        # max_retries: the SDK retries 429/5xx with backoff; keep its default.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)

    async def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[ChatMessage],
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        try:
            async with self._client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            ) as stream:
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
        yield StreamEvent(
            type="usage",
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
        )
