"""AnthropicProvider tool-use plumbing against real SDK message types (no network)."""

from __future__ import annotations

import asyncio
from typing import Any

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from services.ai_assistant.providers.anthropic_provider import AnthropicProvider, _to_api_message
from services.ai_assistant.providers.base import (
    ChatMessage,
    StreamEvent,
    ToolCall,
    ToolResult,
    ToolSpec,
)


class FakeStream:
    def __init__(self, message: Message, deltas: list[str]) -> None:
        self._message = message
        self._deltas = deltas

    async def __aenter__(self) -> FakeStream:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    @property
    def text_stream(self):
        async def gen():
            for delta in self._deltas:
                yield delta

        return gen()

    async def get_final_message(self) -> Message:
        return self._message


def _message(stop_reason: str, content: list[Any]) -> Message:
    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-haiku-5-5",
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=11, output_tokens=7),
    )


def _provider_with(message: Message, deltas: list[str], captured: dict[str, Any]):
    provider = AnthropicProvider("sk-ant-test")

    def fake_stream(**kwargs: Any) -> FakeStream:
        captured.update(kwargs)
        return FakeStream(message, deltas)

    provider._client.messages.stream = fake_stream  # type: ignore[method-assign]
    return provider


def _collect(provider: AnthropicProvider, **kwargs: Any) -> list[StreamEvent]:
    async def go() -> list[StreamEvent]:
        return [
            e
            async for e in provider.stream(
                model="claude-haiku-5-5", system="s", max_tokens=100, **kwargs
            )
        ]

    return asyncio.run(go())


def test_tool_use_turn_yields_tool_calls_raw_blocks_and_usage() -> None:
    content = [
        TextBlock(type="text", text="Let me look."),
        ToolUseBlock(type="tool_use", id="tu_1", name="get_template", input={"template_id": 7}),
    ]
    captured: dict[str, Any] = {}
    provider = _provider_with(_message("tool_use", content), ["Let me look."], captured)
    tool = ToolSpec("get_template", "d", {"type": "object", "properties": {}})

    events = _collect(provider, messages=[ChatMessage(role="user", content="hi")], tools=[tool])

    assert [e.type for e in events] == ["text", "turn"]
    turn = events[1]
    assert turn.stop_reason == "tool_use"
    assert turn.tool_calls == (ToolCall("tu_1", "get_template", {"template_id": 7}),)
    assert turn.raw == content
    assert (turn.input_tokens, turn.output_tokens) == (11, 7)
    assert captured["tools"] == [
        {"name": "get_template", "description": "d", "input_schema": tool.input_schema}
    ]


def test_no_tools_means_no_tools_key_in_the_request() -> None:
    captured: dict[str, Any] = {}
    provider = _provider_with(
        _message("end_turn", [TextBlock(type="text", text="hi")]), ["hi"], captured
    )

    _collect(provider, messages=[ChatMessage(role="user", content="hi")])

    assert "tools" not in captured


def test_refusal_stop_reason_is_an_error() -> None:
    import pytest

    from services.ai_assistant.providers.base import ProviderRefusalError

    provider = _provider_with(_message("refusal", []), [], {})

    with pytest.raises(ProviderRefusalError):
        _collect(provider, messages=[ChatMessage(role="user", content="hi")])


def test_assistant_raw_blocks_and_tool_results_are_sent_back_correctly() -> None:
    raw = [ToolUseBlock(type="tool_use", id="tu_1", name="x", input={})]
    assistant = ChatMessage(role="assistant", content="t", tool_calls=(), raw=raw)
    results = ChatMessage(role="user", tool_results=(ToolResult("tu_1", "out", is_error=True),))

    assert _to_api_message(assistant) == {"role": "assistant", "content": raw}
    assert _to_api_message(results) == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "out", "is_error": True}
        ],
    }
    assert _to_api_message(ChatMessage(role="user", content="plain")) == {
        "role": "user",
        "content": "plain",
    }
