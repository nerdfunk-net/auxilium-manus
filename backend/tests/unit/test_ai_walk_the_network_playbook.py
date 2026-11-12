"""The built-in walk-the-network playbook: it loads, and it matches the step and the tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.ai_assistant import playbooks as pb
from services.ai_assistant.tools import playbook_tools as pt
from services.ai_assistant.tools import run_tools
from workflow_steps.discover_network import crawler

NAME = "walk-the-network"
EMPTY_LOCAL = Path("/nonexistent-local-playbooks")


@pytest.fixture(scope="module")
def playbook() -> pb.Playbook:
    result = pb.load_playbooks(known_tools=pt.known_general_tool_names(), local_dir=EMPTY_LOCAL)
    assert not result.invalid, result.invalid
    found = result.get(NAME)
    assert found is not None
    return found


def test_it_is_a_valid_built_in_playbook_for_everyone(playbook: pb.Playbook) -> None:
    assert playbook.source == "builtin" and playbook.data_class == "A"


def test_it_drives_the_released_workflow_tools_and_nothing_that_touches_a_device(
    playbook: pb.Playbook,
) -> None:
    assert {
        "list_released_workflows",
        "describe_workflow",
        "propose_workflow_run",
        "get_run",
        "get_run_result",
    } <= set(playbook.tools)
    # A walk is the workflow's job: the single-device tools must not stand in for it.
    assert not {t for t in playbook.tools if t.startswith(("propose_neighbor", "propose_device"))}
    assert "propose_workflow_run" in playbook.tools  # the only proposal, and it is a card


def test_every_reason_the_step_can_give_is_explained(playbook: pb.Playbook) -> None:
    reasons = {
        value
        for name, value in vars(crawler).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    assert reasons  # the constants exist
    assert {r for r in reasons if f"`{r}`" not in playbook.body} == set()


def test_every_limit_the_step_can_hit_is_named_or_covered(playbook: pb.Playbook) -> None:
    assert "limits_hit" in playbook.body and "truncated" in playbook.body


def test_the_fields_it_reads_are_the_ones_the_tool_returns(playbook: pb.Playbook) -> None:
    record = {
        "visited": [],
        "seen_not_visited": [],
        "edges": [],
        "limits_hit": [],
        "truncated": False,
    }

    class _Ctx:  # the view only needs the sharing policy
        class sharing:  # noqa: N801
            @staticmethod
            def allows(_cls: object) -> bool:
                return True

    view = run_tools._discovery_view(_Ctx(), record)  # type: ignore[arg-type]
    json.dumps(view)
    for key in ("visited", "seen_not_visited", "seen_by_reason", "links_total", "limits_hit"):
        assert key in view
        assert f"`{key}`" in playbook.body, key
    assert "`truncated`" in playbook.body and "truncated" in view


def test_it_never_offers_to_widen_the_scope_or_run_without_a_confirmation(
    playbook: pb.Playbook,
) -> None:
    text = playbook.body.lower()
    assert "must not offer to widen" in text
    assert "user confirms" in text or "confirm the card" in text
