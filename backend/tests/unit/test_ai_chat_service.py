"""Chat stream + Anthropic error mapping, against a scripted fake provider (no network)."""

from __future__ import annotations

import asyncio

import anthropic
import httpx2
import pytest

from services.ai_assistant.chat_service import ChatEvent, check_connection, stream_chat
from services.ai_assistant.exceptions import AiSettingsValidationError
from services.ai_assistant.providers.anthropic_provider import map_anthropic_error
from services.ai_assistant.providers.base import (
    ChatMessage,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderUnavailableError,
    StreamEvent,
)
from services.ai_assistant.settings_service import AiRuntimeConfig

CONFIG = AiRuntimeConfig(
    provider="anthropic",
    model="claude-haiku-5-5",
    base_url=None,
    api_key="sk-ant-test",
    share_inventory_data=False,
    share_content_data=False,
)
HISTORY = [ChatMessage(role="user", content="hi")]


class ScriptedProvider:
    def __init__(self, events=(), error: Exception | None = None) -> None:
        self.events = list(events)
        self.error = error
        self.calls: list[dict] = []

    async def stream(self, **kwargs):
        self.calls.append(kwargs)
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error


def _factory(provider: ScriptedProvider):
    return lambda *_args, **_kwargs: provider


async def _collect(provider: ScriptedProvider) -> list[ChatEvent]:
    return [e async for e in stream_chat(CONFIG, HISTORY, provider_factory=_factory(provider))]


def test_streams_text_usage_then_done() -> None:
    provider = ScriptedProvider(
        [
            StreamEvent(type="text", text="Hel"),
            StreamEvent(type="text", text="lo"),
            StreamEvent(type="turn", stop_reason="end_turn", input_tokens=5, output_tokens=2),
        ]
    )

    events = asyncio.run(_collect(provider))

    assert [e.event for e in events] == ["text", "text", "usage", "done"]
    assert events[0].data == {"text": "Hel"}
    assert events[2].data == {"input_tokens": 5, "output_tokens": 2}
    assert provider.calls[0]["model"] == "claude-haiku-5-5"


def test_provider_error_becomes_error_event_then_done() -> None:
    provider = ScriptedProvider(error=ProviderRateLimitError("quota reached"))

    events = asyncio.run(_collect(provider))

    assert [e.event for e in events] == ["error", "done"]
    assert events[0].data == {"code": "provider_rate_limited", "message": "quota reached"}


def test_unexpected_error_does_not_leak_details() -> None:
    provider = ScriptedProvider(error=RuntimeError("secret internal detail sk-ant-xyz"))

    events = asyncio.run(_collect(provider))

    assert events[0].event == "error"
    assert "sk-ant-xyz" not in str(events[0].data)
    assert events[0].data["code"] == "internal_error"


def test_check_connection_reports_ok_and_failure() -> None:
    ok = asyncio.run(check_connection(CONFIG, provider_factory=_factory(ScriptedProvider())))
    bad = asyncio.run(
        check_connection(
            CONFIG,
            provider_factory=_factory(ScriptedProvider(error=ProviderAuthError("bad key"))),
        )
    )

    assert ok == {"ok": True}
    assert bad == {"ok": False, "code": "provider_auth", "message": "bad key"}


def _api_error(cls, status: int):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request)
    return cls("raw provider body with sk-ant-leak", response=response, body=None)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_api_error(anthropic.AuthenticationError, 401), ProviderAuthError),
        (_api_error(anthropic.RateLimitError, 429), ProviderRateLimitError),
        (_api_error(anthropic.NotFoundError, 404), ProviderRequestError),
        (_api_error(anthropic.BadRequestError, 400), ProviderRequestError),
        (_api_error(anthropic.InternalServerError, 500), ProviderUnavailableError),
    ],
)
def test_anthropic_errors_are_mapped_and_never_echo_the_body(exc, expected) -> None:
    mapped = map_anthropic_error(exc)

    assert isinstance(mapped, expected)
    assert "sk-ant-leak" not in mapped.message


def _failing_factory(*_args, **_kwargs):
    raise AiSettingsValidationError("Provider 'x' is not available")


def test_missing_adapter_yields_error_then_done_instead_of_a_dead_stream() -> None:
    async def run() -> list[ChatEvent]:
        return [e async for e in stream_chat(CONFIG, HISTORY, provider_factory=_failing_factory)]

    events = asyncio.run(run())

    assert [e.event for e in events] == ["error", "done"]
    assert events[0].data["code"] == "ai_settings_invalid"


def test_missing_adapter_fails_the_connection_check_cleanly() -> None:
    result = asyncio.run(check_connection(CONFIG, provider_factory=_failing_factory))

    assert result["ok"] is False
    assert result["code"] == "ai_settings_invalid"
