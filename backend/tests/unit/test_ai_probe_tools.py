"""``propose_ping_traceroute`` (doc/AI_TOOL_CHAIN.md §51)."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from core.config import settings
from services.ai_assistant import device_token
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.device_access import DeviceNotFoundError, ResolvedDevice
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools import device_tools as dtools
from services.ai_assistant.tools import probe_tools
from services.ai_assistant.tools.base import ToolContext

TARGET = "192.168.178.241"
IOS = ResolvedDevice("nb1", "dev-1", "LAB", "10.1.2.3", "cisco_ios", "cisco_ios")
COMWARE = ResolvedDevice("nb1", "dev-2", "HP", "10.1.2.4", "hp_comware", "hp_comware")


@pytest.fixture(autouse=True)
def _secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "secret_key", "k" * 40)


class FakeResolver:
    def __init__(self, device=IOS, error=None) -> None:
        self.device, self.error = device, error

    async def resolve(self, name):
        if self.error:
            raise self.error
        return self.device


def _ctx(resolver=None):
    return ToolContext(
        user_id=7,
        redactor=Redactor(),
        extras={dtools.DEVICE_RESOLVER_KEY: resolver or FakeResolver()},
        sharing=SharingPolicy(content=True),
    )


def _run(ctx=None, **args):
    (tool,) = probe_tools.build_probe_tools()
    args.setdefault("device", "LAB")
    args.setdefault("target", TARGET)
    return asyncio.run(tool.handler(ctx or _ctx(), tool.input_model(**args)))


def test_the_default_is_a_ping_and_traceroute_only_when_asked() -> None:
    assert _run().proposal["commands"] == [f"ping {TARGET} repeat 5 timeout 2"]


def test_both_proposes_ping_and_traceroute_for_the_target() -> None:
    out = _run(kind="both")

    assert not out.is_error
    assert out.proposal["kind"] == "device_command"
    assert out.proposal["commands"] == [
        f"ping {TARGET} repeat 5 timeout 2",
        f"traceroute {TARGET} numeric timeout 1 probe 1 ttl 1 30",
    ]
    assert out.proposal["parser"] == "none"
    assert out.proposal["device"]["name"] == "LAB"


def test_the_token_carries_the_probe_commands() -> None:
    out = _run(kind="ping", vrf="MGMT", count=3)

    grant = device_token.verify_token(out.proposal["token"], user_id=7)
    assert list(grant.commands) == [f"ping vrf MGMT {TARGET} repeat 3 timeout 2"]


@pytest.mark.parametrize(
    "bad",
    [
        {"target": "example.com"},
        {"target": "127.0.0.1"},
        {"target": f"{TARGET}; reload"},
        {"target": TARGET, "count": 99},
        {"target": TARGET, "vrf": "a b"},
        {"target": TARGET, "source": "lo0"},
        {"target": TARGET, "kind": "flood"},
    ],
)
def test_unsafe_or_unknown_inputs_never_become_a_proposal(bad) -> None:
    try:
        out = _run(**bad)
    except ValidationError:
        return
    assert out.is_error
    assert out.proposal is None


def test_an_unsupported_platform_is_refused_with_a_message() -> None:
    out = _run(_ctx(FakeResolver(COMWARE)))

    assert out.is_error and "Ping and traceroute support" in out.content


def test_an_unknown_device_is_an_error_not_a_proposal() -> None:
    out = _run(_ctx(FakeResolver(error=DeviceNotFoundError())))

    assert out.is_error and out.proposal is None


def test_the_free_form_tool_still_refuses_ping() -> None:
    (tool,) = dtools.build_device_tools()
    out = asyncio.run(
        tool.handler(_ctx(), tool.input_model(device="LAB", commands=[f"ping {TARGET}"]))
    )

    assert out.is_error
