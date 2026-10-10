"""Agent loop + toolbox against a scripted provider (no network)."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict

from services.ai_assistant.agent_loop import MAX_TOOL_STEPS, run_agent
from services.ai_assistant.chat_service import stream_chat
from services.ai_assistant.events import ChatEvent
from services.ai_assistant.providers.base import (
    ChatMessage,
    StreamEvent,
    ToolCall,
)
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.settings_service import AiRuntimeConfig
from services.ai_assistant.tools.base import (
    MAX_TOOL_OUTPUT_CHARS,
    Tool,
    Toolbox,
    ToolContext,
    ToolOutput,
)

CONFIG = AiRuntimeConfig(
    provider="anthropic",
    model="claude-haiku-5-5",
    base_url=None,
    api_key="sk-ant-test",
    share_inventory_data=False,
    share_content_data=False,
)


class Echo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


class ScriptedProvider:
    """Each ``stream`` call plays the next scripted response (a list of StreamEvents)."""

    def __init__(self, responses: list[list[StreamEvent]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        for event in self.responses.pop(0):
            yield event


def _text(text: str) -> StreamEvent:
    return StreamEvent(type="text", text=text)


def _turn(*calls: ToolCall, stop: str = "end_turn", raw: Any = "RAW", i: int = 1, o: int = 1):
    return StreamEvent(
        type="turn",
        tool_calls=tuple(calls),
        stop_reason=stop,
        raw=raw,
        input_tokens=i,
        output_tokens=o,
    )


def _call(id_: str = "t1", name: str = "echo", **input_: Any) -> ToolCall:
    return ToolCall(id=id_, name=name, input=input_ or {"value": "hi"})


def _toolbox(handler=None) -> Toolbox:
    async def default(ctx: ToolContext, args: Echo) -> ToolOutput:
        return ToolOutput(f"echo:{args.value}")

    tool = Tool("echo", "Echo a value", Echo, handler or default)
    return Toolbox([tool], ToolContext(user_id=1, redactor=Redactor()))


def _run(provider: ScriptedProvider, toolbox: Toolbox | None) -> list[ChatEvent]:
    async def go() -> list[ChatEvent]:
        return [
            e
            async for e in run_agent(
                provider=provider,
                model="m",
                system="s",
                messages=[ChatMessage(role="user", content="hi")],
                toolbox=toolbox,
            )
        ]

    return asyncio.run(go())


def test_tool_round_trip_feeds_results_back_and_echoes_raw_blocks() -> None:
    provider = ScriptedProvider(
        [
            [_text("Checking."), _turn(_call(), stop="tool_use", raw="RAW1", i=10, o=3)],
            [_text("Done."), _turn(i=20, o=4)],
        ]
    )

    events = _run(provider, _toolbox())

    names = [(e.event, e.data.get("status") or e.data.get("text")) for e in events]
    assert names == [
        ("text", "Checking."),
        ("tool", "running"),
        ("tool", "done"),
        ("text", "\n\n"),
        ("text", "Done."),
        ("usage", None),
    ]
    assert events[-1].data == {"input_tokens": 30, "output_tokens": 7}
    second = provider.calls[1]["messages"]
    assert second[-2].role == "assistant" and second[-2].raw == "RAW1"
    assert second[-2].tool_calls[0].name == "echo"
    assert second[-1].tool_results[0].content == "echo:hi"
    assert provider.calls[0]["tools"][0].name == "echo"


def test_proposal_goes_to_the_client_but_not_into_the_model_result() -> None:
    async def propose(ctx: ToolContext, args: Echo) -> ToolOutput:
        return ToolOutput("proposal accepted", proposal={"kind": "template", "content": "NEW"})

    provider = ScriptedProvider([[_turn(_call(), stop="tool_use")], [_text("ok"), _turn()]])

    events = _run(provider, _toolbox(propose))

    proposal = [e for e in events if e.event == "proposal"]
    assert proposal[0].data == {"kind": "template", "content": "NEW"}
    assert provider.calls[1]["messages"][-1].tool_results[0].content == "proposal accepted"


def test_step_limit_stops_a_runaway_loop() -> None:
    looping = [[_turn(_call(f"t{i}"), stop="tool_use")] for i in range(MAX_TOOL_STEPS + 3)]
    provider = ScriptedProvider(looping)

    async def go() -> list[ChatEvent]:
        return [
            e
            async for e in stream_chat(
                CONFIG,
                [ChatMessage(role="user", content="hi")],
                provider_factory=lambda *a, **k: provider,
                toolbox=_toolbox(),
            )
        ]

    events = asyncio.run(go())

    assert [e.event for e in events][-2:] == ["error", "done"]
    assert len(provider.calls) == MAX_TOOL_STEPS + 1


def test_cut_off_response_with_tool_call_does_not_run_the_tool() -> None:
    ran: list[str] = []

    async def handler(ctx: ToolContext, args: Echo) -> ToolOutput:
        ran.append(args.value)
        return ToolOutput("x")

    provider = ScriptedProvider([[_turn(_call(), stop="max_tokens")]])

    async def go() -> list[ChatEvent]:
        return [
            e
            async for e in stream_chat(
                CONFIG,
                [ChatMessage(role="user", content="hi")],
                provider_factory=lambda *a, **k: provider,
                toolbox=_toolbox(handler),
            )
        ]

    events = asyncio.run(go())

    assert ran == []
    assert events[0].event == "error"


def test_without_a_toolbox_tool_calls_are_ignored_and_the_turn_ends() -> None:
    provider = ScriptedProvider([[_text("hi"), _turn(_call(), stop="tool_use")]])

    events = _run(provider, None)

    assert [e.event for e in events] == ["text", "usage"]


# -- Toolbox ----------------------------------------------------------------


def _execute(box: Toolbox, call: ToolCall) -> ToolOutput:
    return asyncio.run(box.execute(call))


def test_unknown_tool_and_invalid_input_are_errors_not_exceptions() -> None:
    box = _toolbox()

    assert _execute(box, ToolCall("1", "nope", {})).is_error
    invalid = _execute(box, ToolCall("2", "echo", {"value": 1, "extra": True}))
    assert invalid.is_error and "Invalid input" in invalid.content


def test_handler_exception_is_contained_and_not_leaked() -> None:
    async def boom(ctx: ToolContext, args: Echo) -> ToolOutput:
        raise RuntimeError("db password=hunter2hunter2 exploded")

    out = _execute(_toolbox(boom), _call())

    assert out.is_error
    assert "hunter2" not in out.content and "exploded" not in out.content


def test_output_is_redacted_and_truncated() -> None:
    async def leaky(ctx: ToolContext, args: Echo) -> ToolOutput:
        return ToolOutput("enable secret 5 topsecret123\n" + "x" * (MAX_TOOL_OUTPUT_CHARS + 50))

    out = _execute(_toolbox(leaky), _call())

    assert "topsecret123" not in out.content
    assert out.content.endswith("[output truncated]")
    assert len(out.content) <= MAX_TOOL_OUTPUT_CHARS + 40


def test_tool_spec_is_a_json_schema_object() -> None:
    spec = _toolbox().specs()[0]

    assert spec.input_schema["type"] == "object"
    assert spec.input_schema["properties"]["value"]["type"] == "string"
    assert spec.input_schema["additionalProperties"] is False
