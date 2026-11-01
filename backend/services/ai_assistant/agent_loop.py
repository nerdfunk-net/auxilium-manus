"""The tool loop: call the model, run any tools it asks for, feed results back, repeat.

Runs entirely server-side inside one request. The client never sees tool_use / tool_result
blocks, only neutral ``tool`` status events and ``proposal`` events. Bounded by
``MAX_TOOL_STEPS`` so a confused model cannot loop forever or burn a user's quota.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from services.ai_assistant.events import ChatEvent
from services.ai_assistant.providers.base import (
    ChatMessage,
    LlmProvider,
    ProviderRequestError,
    ProviderUnavailableError,
    StreamEvent,
    ToolResult,
)
from services.ai_assistant.tools.base import Toolbox

MAX_TOOL_STEPS = 8
# No surface may ask for more than this, whatever its budget says (doc/AI_TOOL_CHAIN.md §6.4).
HARD_MAX_TOOL_STEPS = 24
MAX_OUTPUT_TOKENS = 16000


@dataclass(frozen=True)
class RunBudget:
    """Limits for one chat turn. A surface picks its own; the step count is clamped to
    ``HARD_MAX_TOOL_STEPS``. ``max_total_tokens`` counts input plus output tokens of every
    provider call in the turn (input is re-sent each step, so it grows fast); ``max_seconds``
    is wall-clock time since the turn began. ``None`` means no limit of that kind."""

    max_tool_steps: int = MAX_TOOL_STEPS
    max_total_tokens: int | None = None
    max_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_tool_steps < 1:
            raise ValueError("max_tool_steps must be at least 1")
        object.__setattr__(self, "max_tool_steps", min(self.max_tool_steps, HARD_MAX_TOOL_STEPS))


DEFAULT_BUDGET = RunBudget()

_TOO_LONG = "The assistant took too long for one question; please narrow the request"


async def run_agent(
    *,
    provider: LlmProvider,
    model: str,
    system: str,
    messages: list[ChatMessage],
    toolbox: Toolbox | None,
    budget: RunBudget = DEFAULT_BUDGET,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncIterator[ChatEvent]:
    """Yields ``text`` / ``tool`` / ``proposal`` events and a cumulative ``usage`` after every
    provider turn. Provider errors propagate."""
    conversation = list(messages)
    specs = toolbox.specs() if toolbox is not None else []
    input_tokens = 0
    output_tokens = 0
    wrote_text = False
    started = clock()
    max_steps = budget.max_tool_steps

    def time_left() -> float | None:
        """Seconds left in the budget, ``None`` without a time limit; raises once it is used up
        (at exactly ``max_seconds`` too). Read before every model call and every tool, and the
        tool itself is cancelled when it outlives what is left."""
        if budget.max_seconds is None:
            return None
        left = budget.max_seconds - (clock() - started)
        if left <= 0:
            raise ProviderRequestError(_TOO_LONG)
        return left

    for step in range(max_steps + 1):
        time_left()
        turn: StreamEvent | None = None
        step_text: list[str] = []
        separate = wrote_text
        async for event in provider.stream(
            model=model,
            system=system,
            messages=conversation,
            max_tokens=MAX_OUTPUT_TOKENS,
            tools=specs,
        ):
            if event.type == "text":
                if separate and event.text:
                    yield ChatEvent("text", {"text": "\n\n"})
                    separate = False
                step_text.append(event.text)
                wrote_text = wrote_text or bool(event.text)
                yield ChatEvent("text", {"text": event.text})
            else:
                turn = event

        if turn is None:
            raise ProviderUnavailableError("The provider returned no response")
        input_tokens += turn.input_tokens
        output_tokens += turn.output_tokens
        # After every provider turn (cumulative), not once at the end: a turn that then fails
        # (cut off, too many steps) has still spent the tokens, and the audit must see them.
        yield ChatEvent("usage", {"input_tokens": input_tokens, "output_tokens": output_tokens})

        if turn.stop_reason == "max_tokens":
            raise ProviderRequestError("The response was cut off; try a shorter request")
        if not turn.tool_calls or toolbox is None:
            break
        if step == max_steps:
            raise ProviderRequestError(
                "The assistant used too many tool steps; please narrow the request"
            )
        if budget.max_total_tokens is not None and (
            input_tokens + output_tokens > budget.max_total_tokens
        ):
            raise ProviderRequestError(
                "The assistant used too many tokens for one question; please narrow the request"
            )

        conversation.append(
            ChatMessage(
                role="assistant",
                content="".join(step_text),
                tool_calls=turn.tool_calls,
                raw=turn.raw,
            )
        )
        results: list[ToolResult] = []
        for call in turn.tool_calls:
            remaining = time_left()
            yield ChatEvent("tool", {"id": call.id, "name": call.name, "status": "running"})
            try:
                output = await asyncio.wait_for(toolbox.execute(call), timeout=remaining)
            except TimeoutError as exc:
                raise ProviderRequestError(_TOO_LONG) from exc
            yield ChatEvent(
                "tool",
                {
                    "id": call.id,
                    "name": call.name,
                    "status": "error" if output.is_error else "done",
                    "truncated": output.truncated,
                    "withheld": list(output.withheld),
                },
            )
            if output.proposal is not None:
                yield ChatEvent("proposal", output.proposal)
            results.append(ToolResult(call.id, output.content, output.is_error))
        conversation.append(ChatMessage(role="user", tool_results=tuple(results)))
