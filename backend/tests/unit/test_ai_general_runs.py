"""Run explanations in Ask the Net: the run-viewer tools are shared, plus ``list_runs``."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.surfaces import build_general_session
from tests.unit.test_ai_general_surface import FakeReader
from tests.unit.test_ai_run_tools import FakeRunReader

RUN_TOOLS = {
    "get_run",
    "get_step_result",
    "get_artifact",
    "list_run_events",
    "get_run_workflow",
    "list_runs",
}
ROWS = [
    {
        "run_id": 7,
        "workflow_id": 3,
        "workflow_name": "Backup",
        "status": "failed",
        "trigger_type": "manual",
        "started_at": None,
        "finished_at": None,
    }
]


class ListingReader(FakeRunReader):
    def __init__(self, denied: bool = False) -> None:
        super().__init__(denied)
        self.list_calls: list[tuple[Any, ...]] = []

    async def list_runs(self, workflow_id, statuses, limit):
        self._check()
        self.list_calls.append((workflow_id, statuses, limit))
        return ROWS


def _session(run_reader=None, **overrides):
    base = {
        "user_id": 7,
        "reader": FakeReader(),
        "store": ResultStore(InMemoryResultBackend()),
        "sharing": SharingPolicy(),
        "may_query_batfish": True,
        "run_reader": run_reader,
    }
    base.update(overrides)
    return build_general_session(**base)


def _call(session, name: str, **input_: Any):
    return asyncio.run(session.toolbox.execute(ToolCall("1", name, input_)))


def test_run_tools_are_offered_only_with_a_run_reader() -> None:
    assert RUN_TOOLS <= {s.name for s in _session(ListingReader()).toolbox.specs()}
    assert not RUN_TOOLS & {s.name for s in _session(None).toolbox.specs()}


def test_run_tools_do_not_need_batfish() -> None:
    session = _session(ListingReader(), may_query_batfish=False)
    assert RUN_TOOLS <= {s.name for s in session.toolbox.specs()}
    assert "run" in session.system.lower()


def test_prompt_mentions_runs_only_with_a_reader() -> None:
    assert "list_runs" in _session(ListingReader()).system
    assert "list_runs" not in _session(None).system


def test_no_run_open_points_to_list_runs() -> None:
    out = _call(_session(ListingReader()), "get_run")
    assert out.is_error and "list_runs" in out.content


def test_get_run_works_by_id_and_hides_content_without_opt_in() -> None:
    out = _call(_session(ListingReader()), "get_run", run_id=7)
    data = json.loads(out.content)
    assert data["id"] == 7
    assert data["error_message"]["not_shared"] == "content_data"
    assert "10.0.0.9" not in out.content


def test_list_runs_returns_metadata_and_passes_filters() -> None:
    reader = ListingReader()
    out = _call(_session(reader), "list_runs", workflow_id=3, status="failed", limit=5)
    data = json.loads(out.content)
    assert data["runs"][0]["run_id"] == 7
    assert reader.list_calls == [(3, ["failed"], 5)]


def test_list_runs_defaults() -> None:
    reader = ListingReader()
    _call(_session(reader), "list_runs")
    assert reader.list_calls == [(None, None, 10)]


@pytest.mark.parametrize("bad", [{"limit": 0}, {"limit": 21}, {"status": "bogus"}, {"path": "x"}])
def test_list_runs_rejects_bad_input(bad) -> None:
    reader = ListingReader()
    out = _call(_session(reader), "list_runs", **bad)
    assert out.is_error and reader.list_calls == []


def test_list_runs_denied_gives_the_fixed_message() -> None:
    out = _call(_session(ListingReader(denied=True)), "list_runs")
    assert out.is_error and "cannot access" in out.content


def test_list_runs_adds_audit_refs() -> None:
    session = _session(ListingReader())
    _call(session, "list_runs")
    assert "run:7" in session.toolbox.audit_refs


# -- review fixes (doc/analysis/REVIEW.md) ----------------------------------------------------


def _run(run_id: int, names: list[str]) -> dict[str, Any]:
    devices = {n: {"id": n, "name": n, "status": "failed"} for n in names}
    step = {
        "step_node_id": "cmd-1",
        "step_type": "send-commands",
        "step_name": "Run",
        "status": "failed",
        "output": {"outcomes": {"failed": {"devices": devices}}},
    }
    return {
        "id": run_id,
        "workflow_id": 3,
        "status": "failed",
        "trigger_type": "manual",
        "step_results": [step],
        "device_groups": [],
    }


class TwoRunReader(ListingReader):
    async def get_run(self, run_id):
        return {7: _run(7, ["sw-a", "sw-b"]), 8: _run(8, ["sw-z"])}[run_id]


def _devices(out) -> list[str]:
    return [d["device"] for d in json.loads(out.content)["outcomes"]["failed"]]


def test_device_labels_do_not_depend_on_which_other_run_was_loaded() -> None:
    reader = TwoRunReader()
    first = _session(reader)  # turn 1: run 8 first, then run 7
    _call(first, "get_run", run_id=8)
    turn1 = _devices(_call(first, "get_step_result", run_id=7, node_id="cmd-1"))
    second = _session(reader)  # turn 2: a fresh request that loads run 7 only
    turn2 = _devices(_call(second, "get_step_result", run_id=7, node_id="cmd-1"))

    assert turn1 == turn2 == ["device-1", "device-2"]
    filtered = _call(second, "get_step_result", run_id=7, node_id="cmd-1", device="device-2")
    assert _devices(filtered) == ["device-2"]


def test_runs_only_session_does_not_claim_nautobot() -> None:
    system = _session(ListingReader(), may_query_batfish=False).system
    assert "only the run tools" in system
    assert "Nautobot" not in system.split("Data the user shares")[-1]


def test_no_tools_prompt_when_nothing_is_offered() -> None:
    assert "no tools" in _session(None, may_query_batfish=False).system


def test_run_viewer_surface_has_no_list_runs_and_does_not_name_it() -> None:
    from models.ai_assistant import RunViewerContext
    from services.ai_assistant.surfaces import build_run_viewer_session
    from tests.unit.test_ai_run_tools import FakeRunReader as PageReader

    session = build_run_viewer_session(
        user_id=1,
        context=RunViewerContext(surface="run_viewer", run_id=None),
        reader=PageReader(),
        sharing=SharingPolicy(),
    )
    assert "list_runs" not in {s.name for s in session.toolbox.specs()}
    out = _call(session, "get_run")
    assert out.is_error and "list_runs" not in out.content
