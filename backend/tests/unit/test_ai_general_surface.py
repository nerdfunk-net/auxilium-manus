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

READ_PREFIXES = ("get_", "list_", "query_", "fetch_")
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
        "query_result",
        "fetch_slice",
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
