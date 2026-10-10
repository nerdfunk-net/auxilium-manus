"""Provider-neutral types for the in-app AI assistant.

Vendors differ only inside an adapter. Everything above this module (chat service, tools,
router) sees ``ChatMessage`` in and ``StreamEvent`` out, and a small set of
``ProviderError`` subclasses whose messages are safe to show a user (never a raw
provider response body). doc/ai_integration/AI_ASSISTANT.md §3.1.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class StreamEvent:
    """``text``: a delta in ``text``. ``usage``: final token counts."""

    type: Literal["text", "usage"]
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderError(Exception):
    """A failure the user can act on. ``code`` is stable; ``message`` is safe to display."""

    code = "provider_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProviderAuthError(ProviderError):
    code = "provider_auth"


class ProviderRateLimitError(ProviderError):
    """Rate limit or quota exhausted (e.g. a free tier). Never retried in a tight loop."""

    code = "provider_rate_limited"


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"


class ProviderRequestError(ProviderError):
    """Bad request: unknown model, context too long, invalid parameters."""

    code = "provider_bad_request"


class ProviderRefusalError(ProviderError):
    code = "provider_refused"


class LlmProvider(Protocol):
    def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[ChatMessage],
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]: ...
