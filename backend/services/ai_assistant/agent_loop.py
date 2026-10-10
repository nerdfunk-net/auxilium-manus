"""The tool loop: call the model, run any tools it asks for, feed results back, repeat.

Runs entirely server-side inside one request. The client never sees tool_use / tool_result
blocks, only neutral ``tool`` status events and ``proposal`` events. Bounded by
``MAX_TOOL_STEPS`` so a confused model cannot loop forever or burn a user's quota.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

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
MAX_OUTPUT_TOKENS = 16000


async def run_agent(
    *,
    provider: LlmProvider,
    model: str,
    system: str,
    messages: list[ChatMessage],
    toolbox: Toolbox | None,
) -> AsyncIterator[ChatEvent]:
    """Yields ``text`` / ``tool`` / ``proposal`` / ``usage`` events. Provider errors propagate."""
    conversation = list(messages)
    specs = toolbox.specs() if toolbox is not None else []
    input_tokens = 0
    output_tokens = 0
    wrote_text = False

    for step in range(MAX_TOOL_STEPS + 1):
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

        if turn.stop_reason == "max_tokens":
            raise ProviderRequestError("The response was cut off; try a shorter request")
        if not turn.tool_calls or toolbox is None:
            break
        if step == MAX_TOOL_STEPS:
            raise ProviderRequestError(
                "The assistant used too many tool steps; please narrow the request"
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
            yield ChatEvent("tool", {"id": call.id, "name": call.name, "status": "running"})
            output = await toolbox.execute(call)
            yield ChatEvent(
                "tool",
                {
                    "id": call.id,
                    "name": call.name,
                    "status": "error" if output.is_error else "done",
                },
            )
            if output.proposal is not None:
                yield ChatEvent("proposal", output.proposal)
            results.append(ToolResult(call.id, output.content, output.is_error))
        conversation.append(ChatMessage(role="user", tool_results=tuple(results)))

    yield ChatEvent("usage", {"input_tokens": input_tokens, "output_tokens": output_tokens})
