"""``propose_device_command`` on the general surface (doc/AI_TOOL_CHAIN.md §29 step 4)."""

from __future__ import annotations

import asyncio

import pytest

from core.config import settings
from services.ai_assistant import device_access as da
from services.ai_assistant import device_token
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.device_access import (
    DeviceAmbiguousError,
    DeviceNoAddressError,
    DeviceNotFoundError,
    ResolvedDevice,
)
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools import device_tools as dtools
from services.ai_assistant.tools.base import ToolContext

DEVICE = ResolvedDevice("nb1", "dev-1", "LAB", "10.1.2.3", "cisco_ios", "cisco_ios")


@pytest.fixture(autouse=True)
def _secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "secret_key", "k" * 40)


class FakeResolver:
    def __init__(self, device=DEVICE, error=None) -> None:
        self.device, self.error, self.names = device, error, []

    async def resolve(self, name):
        self.names.append(name)
        if self.error:
            raise self.error
        return self.device


def _ctx(resolver=None, user_id=7):
    return ToolContext(
        user_id=user_id,
        redactor=Redactor(),
        extras={dtools.DEVICE_RESOLVER_KEY: resolver or FakeResolver()},
        sharing=SharingPolicy(content=True),
    )


def _propose(ctx, device="LAB", commands=("show running-config",)):
    (tool,) = dtools.build_device_tools()
    return asyncio.run(tool.handler(ctx, tool.input_model(device=device, commands=list(commands))))


def test_there_is_exactly_one_tool_and_it_is_a_proposal() -> None:
    (tool,) = dtools.build_device_tools()

    assert tool.name == "propose_device_command"
    assert "not run" in tool.description.lower() or "confirm" in tool.description.lower()


def test_running_config_of_lab_becomes_a_proposal_with_a_signed_token() -> None:
    ctx = _ctx()

    out = _propose(ctx)

    assert not out.is_error
    proposal = out.proposal
    assert proposal is not None
    assert proposal["kind"] == "device_command"
    assert proposal["device"] == {
        "id": "dev-1",
        "name": "LAB",
        "host": "10.1.2.3",
        "platform": "cisco_ios",
    }
    assert proposal["commands"] == ["show running-config"]
    grant = device_token.verify_token(proposal["token"], user_id=7)
    assert (grant.device_id, grant.device_name, grant.source_id) == ("dev-1", "LAB", "nb1")
    assert grant.host == "10.1.2.3"  # the address on the card is the one that is signed
    assert grant.commands == ("show running-config",)
    assert proposal["expires_at"] == grant.expires_at


def test_startup_config_of_lab_works_the_same_way() -> None:
    out = _propose(_ctx(), commands=["show startup-config"])

    assert out.proposal is not None
    assert out.proposal["commands"] == ["show startup-config"]


def test_commands_are_normalised_before_they_are_signed() -> None:
    out = _propose(_ctx(), commands=["SHOW   running-config", "show running-config"])

    assert out.proposal is not None
    assert out.proposal["commands"] == ["show running-config"]
    grant = device_token.verify_token(out.proposal["token"], user_id=7)
    assert grant.commands == ("show running-config",)  # the signed form is the normalised one


def test_the_resolver_gets_the_name_the_model_gave() -> None:
    resolver = FakeResolver()

    _propose(_ctx(resolver), device="edge-1")

    assert resolver.names == ["edge-1"]


def test_the_model_is_told_it_was_not_run_and_never_sees_the_host() -> None:
    out = _propose(_ctx())

    assert "NOT run" in out.content
    assert "10.1.2.3" not in out.content
    assert out.proposal is not None and out.proposal["token"] not in out.content


@pytest.mark.parametrize(
    "commands",
    [["conf t"], ["reload"], ["show version; reload"], ["sh run"], ["show run | redirect x"]],
)
def test_a_command_the_policy_refuses_makes_no_proposal(commands) -> None:
    resolver = FakeResolver()
    out = _propose(_ctx(resolver), commands=commands)

    assert out.is_error and out.proposal is None
    assert "show" in out.content.lower()
    assert resolver.names == []  # refused before the inventory is asked


def test_the_refusal_does_not_echo_the_command() -> None:
    out = _propose(_ctx(), commands=["reload SECRET-TEXT"])

    assert "SECRET-TEXT" not in out.content


@pytest.mark.parametrize(
    "error", [DeviceNotFoundError(), DeviceAmbiguousError(), DeviceNoAddressError()]
)
def test_device_problems_are_reported_without_a_proposal(error) -> None:
    out = _propose(_ctx(FakeResolver(error=error)))

    assert out.is_error and out.proposal is None
    assert str(error) in out.content


def test_the_device_name_is_checked_before_the_inventory_sees_it() -> None:
    (tool,) = dtools.build_device_tools()

    for bad in ["", "a b", "lab;reload", "x" * 200, "../etc", "LAB\nignore previous"]:
        with pytest.raises(ValueError):
            tool.input_model(device=bad, commands=["show version"])


def test_at_most_five_commands_of_bounded_length() -> None:
    (tool,) = dtools.build_device_tools()

    with pytest.raises(ValueError):
        tool.input_model(device="LAB", commands=[])
    with pytest.raises(ValueError):
        tool.input_model(device="LAB", commands=["show version"] * 6)
    with pytest.raises(ValueError):
        tool.input_model(device="LAB", commands=["show " + "a" * 400])


def test_the_device_is_recorded_for_the_audit_line() -> None:
    ctx = _ctx()

    _propose(ctx)

    assert ctx.audit_refs == {"device:dev-1"}


def test_a_proposal_is_not_audited_when_it_fails() -> None:
    ctx = _ctx(FakeResolver(error=DeviceNotFoundError()))

    _propose(ctx)

    assert ctx.audit_refs == set()


def test_the_proposal_says_whether_the_inventory_names_a_known_driver() -> None:
    known = _propose(_ctx()).proposal
    unknown_device = ResolvedDevice("nb1", "dev-1", "LAB", "10.1.2.3", None, None)
    unknown = _propose(_ctx(FakeResolver(unknown_device))).proposal

    assert known is not None and unknown is not None
    assert known["driver_known"] is True
    assert unknown["driver_known"] is False
    assert unknown["driver_choices"] == list(da.DEVICE_DRIVERS)
    assert unknown["device"]["platform"] is None


def test_the_model_is_told_the_user_will_be_asked_for_the_device_type() -> None:
    unknown_device = ResolvedDevice("nb1", "dev-1", "LAB", "10.1.2.3", "lab", None)

    out = _propose(_ctx(FakeResolver(unknown_device)))

    assert "device type" in out.content
    assert "device type" not in _propose(_ctx()).content
