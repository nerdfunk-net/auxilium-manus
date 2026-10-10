"""Provider-neutral types for the in-app AI assistant.

Vendors differ only inside an adapter. Everything above this module (chat service, tools,
router) sees ``ChatMessage`` in and ``StreamEvent`` out, and a small set of
``ProviderError`` subclasses whose messages are safe to show a user (never a raw
provider response body). doc/ai_integration/AI_ASSISTANT.md §3.1.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may call. ``input_schema`` is a JSON Schema object."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ChatMessage:
    """One conversation turn.

    Plain chat uses only ``role`` + ``content``. Inside one tool-loop request an assistant turn
    also carries ``tool_calls`` and the following user turn carries ``tool_results``. ``raw`` is
    the provider's own assistant content (e.g. thinking blocks), opaque to everything but the
    adapter that produced it, which echoes it back unchanged when continuing after a tool call.
    """

    role: Literal["user", "assistant"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    raw: Any = field(default=None, repr=False)


@dataclass(frozen=True)
class StreamEvent:
    """``text``: a delta in ``text``. ``turn``: the model finished one response; carries any
    tool calls, the stop reason, the provider-opaque ``raw`` content and token counts."""

    type: Literal["text", "turn"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: str = ""
    raw: Any = field(default=None, repr=False)
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
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[StreamEvent]: ...
