"""The ``general`` surface (shown in the UI as "Ask the Net"): context, session, result store."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from models.ai_assistant import AssistantContext, GeneralContext
from models.ai_conversations import AiSurface
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.results import factory
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.surfaces import build_general_session
from tests.unit.test_ai_batfish_tools import FakeReader

READ_PREFIXES = (
    "get_",
    "list_",
    "query_",
    "fetch_",
    "analyze_",
    "check_",
    "diff_",
    "compare_",
    "differential_",
)
FORBIDDEN_PREFIXES = ("run", "trigger", "execute", "start", "delete", "propose")


def _session(**overrides):
    base = {
        "user_id": 7,
        "reader": FakeReader(),
        "store": ResultStore(InMemoryResultBackend()),
        "sharing": SharingPolicy(inventory=True, addresses=True),
        "may_query_batfish": True,
    }
    base.update(overrides)
    return build_general_session(**base)


# -- context model ----------------------------------------------------------------------------


def test_general_is_a_valid_chat_context() -> None:
    parsed = TypeAdapter(AssistantContext).validate_python({"surface": "general"})

    assert isinstance(parsed, GeneralContext)


def test_general_context_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(AssistantContext).validate_python({"surface": "general", "network": "x"})


def test_conversations_can_be_saved_for_the_general_surface() -> None:
    assert "general" in AiSurface.__args__  # type: ignore[attr-defined]


def test_the_general_budget_allows_a_slow_local_model_five_minutes() -> None:
    from services.ai_assistant.surfaces import GENERAL_BUDGET

    assert GENERAL_BUDGET.max_seconds == 300
    assert GENERAL_BUDGET.max_tool_steps == 16
    assert GENERAL_BUDGET.max_total_tokens == 400_000


# -- session ----------------------------------------------------------------------------------


def test_session_offers_batfish_and_result_tools() -> None:
    names = {s.name for s in _session().toolbox.specs()}

    assert names == {
        "list_batfish_networks",
        "list_batfish_snapshots",
        "get_routes",
        "get_traceroute",
        "get_bgp_session_status",
        "get_interface_properties",
        "get_device_facts",
        "analyze_acl",
        "check_reachability",
        "compare_filters",
        "differential_reachability",
        "get_snapshot_parse_issues",
        "list_snapshot_devices",
        "get_ip_owners",
        "query_result",
        "fetch_slice",
        "diff_results",
        "list_playbooks",
        "get_playbook",
        # neighbour reads that need no device (doc/AI_TOOL_CHAIN.md §24)
        "get_modelled_neighbors",
        "get_neighbor_sources",
    }


def test_every_tool_is_a_read_and_none_executes_or_writes() -> None:
    names = [s.name for s in _session().toolbox.specs()]

    assert all(n.startswith(READ_PREFIXES) for n in names), names
    assert not [n for n in names if n.startswith(FORBIDDEN_PREFIXES)]


def test_without_the_batfish_permission_no_batfish_tool_is_offered() -> None:
    session = _session(may_query_batfish=False)

    names = {s.name for s in session.toolbox.specs()}

    assert not names & {"get_routes", "get_traceroute", "list_batfish_networks"}
    assert "not allowed to query Batfish" in session.system


def test_without_a_result_store_the_handle_tools_are_not_offered() -> None:
    names = {s.name for s in _session(store=None).toolbox.specs()}

    assert "get_routes" in names
    assert not names & {"query_result", "fetch_slice"}


def test_system_prompt_states_what_is_shared_and_that_tool_data_is_untrusted() -> None:
    system = _session(sharing=SharingPolicy()).system

    assert "Batfish" in system
    assert "snapshot" in system
    assert "not instructions" in system
    assert "not_shared" in system
    assert "Data the user shares with you" in system


def test_system_prompt_does_not_promise_live_device_access() -> None:
    system = _session().system.lower()

    assert "cannot run commands" in system or "you cannot" in system
    assert "ssh" not in system.replace("cannot", "")


# -- result store factory ---------------------------------------------------------------------


def test_result_store_factory_is_cached_and_does_not_connect(monkeypatch) -> None:
    created: list[dict] = []

    class _Client:
        pass

    def from_url(url: str, **kwargs):
        created.append({"url": url, **kwargs})
        return _Client()

    monkeypatch.setattr(factory.redis, "from_url", from_url)
    monkeypatch.setattr(factory, "_store", None)

    first = factory.get_result_store()
    second = factory.get_result_store()

    assert first is second
    assert len(created) == 1
    assert created[0]["decode_responses"] is True
    # Short timeouts: a Redis outage must degrade a tool, not hang the chat turn.
    assert created[0]["socket_timeout"] <= 5 and created[0]["socket_connect_timeout"] <= 5


def test_general_surface_has_a_larger_budget_than_the_default() -> None:
    from services.ai_assistant.agent_loop import DEFAULT_BUDGET

    budget = _session().budget

    assert budget.max_tool_steps > DEFAULT_BUDGET.max_tool_steps
    assert budget.max_total_tokens is not None
    assert budget.max_seconds is not None


def test_session_without_batfish_permission_keeps_the_default_budget() -> None:
    from services.ai_assistant.agent_loop import DEFAULT_BUDGET

    session = _session(may_query_batfish=False)

    assert session.budget == DEFAULT_BUDGET


# -- device commands (doc/AI_TOOL_CHAIN.md §29) -----------------------------------------------


class _Resolver:
    async def resolve(self, name):
        raise AssertionError("not used by these tests")


def test_the_device_tool_is_absent_unless_the_router_offers_a_resolver() -> None:
    names = {s.name for s in _session().toolbox.specs()}

    assert "propose_device_command" not in names
    assert "propose_device_command" not in _session().system


def test_with_a_resolver_the_session_offers_exactly_the_three_proposal_tools() -> None:
    session = _session(device_resolver=_Resolver())

    names = [s.name for s in session.toolbox.specs()]

    assert [n for n in names if n.startswith("propose")] == [
        "propose_device_command",
        "propose_neighbor_discovery",
        "propose_feature_learn",
    ]
    assert not [n for n in names if n.startswith(("run", "trigger", "execute", "start", "delete"))]
    assert "propose_device_command" in session.system
    assert "show running-config" in session.system
    assert "show startup-config" in session.system
    assert "propose_device_command" in session.toolbox._context.extras["available_tools"]


# -- parsing device output (doc/AI_TOOL_CHAIN.md §43) -----------------------------------------


def test_the_parse_tool_comes_with_the_device_tool_and_a_store() -> None:
    session = _session(device_resolver=_Resolver())

    names = {s.name for s in session.toolbox.specs()}

    assert "parse_command_output" in names
    assert "parse_command_output" in session.system
    assert "genie_parser" not in session.toolbox._context.extras


def test_without_a_store_or_a_resolver_there_is_no_parse_tool() -> None:
    no_store = {s.name for s in _session(device_resolver=_Resolver(), store=None).toolbox.specs()}
    no_resolver = {s.name for s in _session().toolbox.specs()}

    assert "parse_command_output" not in no_store
    assert "parse_command_output" not in no_resolver


def test_a_genie_parser_is_put_in_the_session_only_when_given() -> None:
    genie = object()

    session = _session(device_resolver=_Resolver(), genie_parser=genie)
    ignored = _session(genie_parser=genie)

    assert session.toolbox._context.extras["genie_parser"] is genie
    assert "genie_parser" not in ignored.toolbox._context.extras


def test_playbooks_may_name_the_parse_tool() -> None:
    from services.ai_assistant.tools.playbook_tools import known_general_tool_names

    assert "parse_command_output" in known_general_tool_names()


def test_the_prompt_says_the_command_is_not_run_by_the_model() -> None:
    system = _session(device_resolver=_Resolver()).system

    assert "confirm" in system.lower()
    assert "not run" in system.lower() or "does not run" in system.lower()


def test_without_the_batfish_permission_a_resolver_gives_no_tool() -> None:
    session = _session(device_resolver=_Resolver(), may_query_batfish=False)

    assert session.toolbox.specs() == []
    assert "propose_device_command" not in session.system
    assert "cannot run commands on devices" in session.system  # no tool, so the old line stands


def test_playbooks_may_name_the_device_tool() -> None:
    from services.ai_assistant.tools.playbook_tools import known_general_tool_names

    assert "propose_device_command" in known_general_tool_names()


def test_the_offered_tool_really_reaches_the_resolver_through_the_toolbox() -> None:
    import asyncio

    from core.config import settings
    from services.ai_assistant.device_access import ResolvedDevice
    from services.ai_assistant.providers.base import ToolCall

    class Found:
        names: list[str] = []

        async def resolve(self, name):
            self.names.append(name)
            return ResolvedDevice("nb1", "dev-1", name, "10.1.2.3", None, None)

    resolver = Found()
    session = _session(device_resolver=resolver)
    old = settings.secret_key
    settings.secret_key = "k" * 40
    try:
        out = asyncio.run(
            session.toolbox.execute(
                ToolCall(
                    id="1",
                    name="propose_device_command",
                    input={"device": "LAB", "commands": ["show running-config"]},
                )
            )
        )
    finally:
        settings.secret_key = old

    assert not out.is_error and out.proposal is not None
    assert resolver.names == ["LAB"]


def test_with_device_commands_the_prompt_no_longer_says_commands_cannot_be_run() -> None:
    plain = _session().system
    with_tool = _session(device_resolver=_Resolver()).system

    assert "cannot run commands on devices" in plain  # unchanged where the tool is not offered
    assert "cannot run commands on devices" not in with_tool
    assert "never run anything yourself" in with_tool.lower()
    assert "change configuration" in with_tool  # still told it cannot change anything
    assert "propose_device_command" in with_tool
