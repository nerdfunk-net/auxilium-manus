"""Feature learn (doc/AI_TOOL_CHAIN.md §49): catalogue, command limit, proposal."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from core.config import settings
from services.ai_assistant import device_token
from services.ai_assistant.command_policy import (
    MAX_COMMANDS,
    MAX_SIGNED_COMMANDS,
    CommandNotAllowedError,
    check_command,
    check_commands,
)
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.device_access import DeviceNotFoundError, ResolvedDevice
from services.ai_assistant.learn import catalogue
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.base import ToolContext, ToolOutput
from services.ai_assistant.tools.device_tools import (
    DEVICE_RESOLVER_KEY,
    GENIE_PARSER_KEY,
    build_device_tools,
)
from services.ai_assistant.tools.learn_tools import build_learn_tools

USER = 7
IOS = ResolvedDevice("nb1", "dev-1", "LAB", "10.1.2.3", "cisco_ios", "cisco_ios")
NXOS = ResolvedDevice("nb1", "dev-2", "NX1", "10.1.2.4", "cisco_nxos", "cisco_nxos")


@pytest.fixture(autouse=True)
def _secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "secret_key", "k" * 40)


class FakeResolver:
    def __init__(self, device: ResolvedDevice | None = IOS):
        self.device = device

    async def resolve(self, name: str) -> ResolvedDevice:
        if self.device is None:
            raise DeviceNotFoundError
        return self.device


def _ctx(resolver: Any = None, **extras: Any) -> ToolContext:
    return ToolContext(
        user_id=USER,
        redactor=Redactor(),
        extras={DEVICE_RESOLVER_KEY: resolver or FakeResolver(), **extras},
        sharing=SharingPolicy(inventory=True, addresses=True, content=True),
    )


def _call(ctx: ToolContext, **args: Any) -> ToolOutput:
    tool = build_learn_tools()[0]
    return asyncio.run(tool.handler(ctx, tool.input_model(**args)))


def test_every_catalogued_command_passes_the_read_only_policy() -> None:
    for family in ("ios",):
        for feature in catalogue.supported(family):
            plan = catalogue.plan_learn(family, feature)
            assert len(plan.commands) <= MAX_SIGNED_COMMANDS
            assert len(set(plan.commands)) == len(plan.commands)
            for command in plan.commands:
                assert check_command(command) == command


def test_ospf_plan_is_longer_than_a_free_form_proposal_may_be() -> None:
    plan = catalogue.plan_learn("ios", "ospf")

    assert len(plan.commands) > MAX_COMMANDS
    with pytest.raises(CommandNotAllowedError):
        check_commands(list(plan.commands))
    assert check_commands(list(plan.commands), limit=MAX_SIGNED_COMMANDS) == list(plan.commands)


def test_free_form_proposal_keeps_its_five_command_limit() -> None:
    model = build_device_tools()[0].input_model
    with pytest.raises(ValueError):  # noqa: PT011 - pydantic ValidationError is a ValueError
        model(device="LAB", commands=["show version"] * (MAX_COMMANDS + 1))


def test_unsupported_family_and_feature_are_refused() -> None:
    with pytest.raises(catalogue.UnsupportedLearnError):
        catalogue.plan_learn("nxos", "ospf")
    with pytest.raises(catalogue.UnsupportedLearnError):
        catalogue.plan_learn(None, "ospf")
    with pytest.raises(catalogue.UnsupportedLearnError):
        catalogue.plan_learn("ios", "eigrp")


def test_proposal_is_a_signed_device_command_card_without_genie() -> None:
    out = _call(_ctx(), device="LAB", feature="ospf")

    assert not out.is_error and out.proposal is not None
    assert out.proposal["kind"] == "device_command"
    assert out.proposal["commands"] == list(catalogue.plan_learn("ios", "ospf").commands)
    assert out.proposal["parser"] == "none"
    grant = device_token.verify_token(out.proposal["token"], user_id=USER)
    assert grant.commands == tuple(out.proposal["commands"])
    assert "not parsed" in out.content


def test_proposal_asks_for_genie_parsing_when_genie_is_offered() -> None:
    out = _call(_ctx(**{GENIE_PARSER_KEY: object()}), device="LAB", feature="ospf")

    assert out.proposal is not None
    assert out.proposal["parser"] == "genie"
    assert device_token.verify_token(out.proposal["token"], user_id=USER).parser == "genie"


def test_unsupported_platform_is_refused_and_nothing_is_signed() -> None:
    out = _call(_ctx(FakeResolver(NXOS)), device="NX1", feature="ospf")

    assert out.is_error and out.proposal is None
    assert "IOS" in out.content


def test_unknown_device_is_reported() -> None:
    out = _call(_ctx(FakeResolver(None)), device="nope", feature="ospf")

    assert out.is_error and out.proposal is None


def test_unknown_feature_is_rejected_by_the_input_model() -> None:
    model = build_learn_tools()[0].input_model
    with pytest.raises(ValueError):  # noqa: PT011
        model(device="LAB", feature="eigrp")


def test_bgp_plan_has_only_static_commands_and_no_route_tables() -> None:
    plan = catalogue.plan_learn("ios", "bgp")

    assert "show bgp all summary" in plan.commands
    assert not [c for c in plan.commands if "routes" in c or "<" in c or "{" in c]


def test_bgp_proposal_points_at_the_bgp_playbook() -> None:
    out = _call(_ctx(), device="LAB", feature="bgp")

    assert out.proposal is not None
    assert out.proposal["commands"] == list(catalogue.plan_learn("ios", "bgp").commands)
    assert "learn-bgp-of-a-device" in out.content


def test_small_outputs_come_first_and_the_database_dumps_last() -> None:
    ospf = catalogue.plan_learn("ios", "ospf").commands
    last_small = max(
        ospf.index(c) for c in ("show ip ospf interface", "show ip ospf neighbor detail")
    )
    first_dump = min(i for i, c in enumerate(ospf) if c.startswith("show ip ospf database"))
    assert last_small < first_dump
    assert catalogue.plan_learn("ios", "bgp").commands[-1] == "show bgp all detail"


def test_only_a_catalogue_plan_may_exceed_the_free_form_limit() -> None:
    plan = catalogue.plan_learn("ios", "ospf").commands

    assert catalogue.is_plan(plan)
    assert catalogue.is_plan(list(plan))
    assert not catalogue.is_plan(plan[:-1])
    assert not catalogue.is_plan((*plan[:-1], "show version"))
    assert not catalogue.is_plan(("show version",) * 6)


def test_run_budget_grows_only_for_commands_beyond_five() -> None:
    from services.ai_assistant import device_exec_service as ex

    assert ex.run_budget_seconds(1) == ex.RUN_TIMEOUT_SECONDS
    assert ex.run_budget_seconds(5) == ex.RUN_TIMEOUT_SECONDS
    assert ex.run_budget_seconds(13) == ex.RUN_TIMEOUT_SECONDS + 8 * ex.EXTRA_SECONDS_PER_COMMAND


def test_learn_database_shows_get_the_long_read_timeout() -> None:
    from services.ai_assistant.device_access import _LONG_COMMANDS

    for feature in catalogue.FEATURES:
        for command in catalogue.plan_learn("ios", feature).commands:
            if command.startswith(("show ip ospf database", "show bgp all detail")):
                assert command.lower().startswith(_LONG_COMMANDS), command
