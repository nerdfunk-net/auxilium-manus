"""Characterization tests for the execution paths the package split moves but
which have NO other unit coverage today (doc/refactoring/STEPRUNNER_WORKFLOWRUN.md
§6.1 R5 gap table):

* ``StepRunner.execute_subgraph`` — fan-out child subgraph walk (moves to
  ``step_runner/subgraph.py`` in Phase 1e).
* ``StepRunner.resume_after_join`` — post-fan-in resume (moves to
  ``step_runner/runner.py`` in Phase 1d).
* ``_finalize_fan_out_parent`` — child aggregation + post-join resume wiring
  (moves to ``workflow_run/aggregation.py`` in Phase 2b).
* ``_run_steps_until_fan_out_or_done`` fan-out signal payload (the
  ``_fan_out_context_if_requested`` branch moves to ``workflow_run/phase1.py``
  in Phase 2e).

These pin observable behaviour (executed node order, persisted
WorkflowStepResult rows, return values, FanOutSignal shape) so any accidental
logic change during a "pure move" fails here.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from hatchet.workflows.workflow_run import (
    _finalize_fan_out_parent,
    _run_steps_until_fan_out_or_done,
)
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from repositories.run_repository import RunRepository
from services.execution.step_runner import FanOutSignal, StepRunner


def _node(node_id: str, kind: str) -> dict[str, Any]:
    return {"id": node_id, "data": {"kind": kind, "title": kind}}


def _edge(source: str, target: str, source_handle: str | None = None) -> dict[str, Any]:
    edge: dict[str, Any] = {"source": source, "target": target}
    if source_handle is not None:
        edge["sourceHandle"] = source_handle
    return edge


def _make_session() -> tuple[Session, Any]:
    engine = create_engine("sqlite:///:memory:")
    WorkflowRun.metadata.create_all(
        engine,
        tables=[User.__table__, WorkflowRun.__table__, WorkflowStepResult.__table__],
    )
    return sessionmaker(bind=engine)(), engine


def _make_run(db: Session) -> WorkflowRun:
    run = WorkflowRun(
        uuid="run-uuid-1",
        workflow_id=1,
        triggered_by_id=None,
        status="running",
        trigger_type="manual",
        run_mode="normal",
        device_ids=[],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _device(did: str) -> DeviceContext:
    return DeviceContext(
        id=did,
        name=did,
        hostname=did,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _ctx(devices: dict[str, DeviceContext] | None = None) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="1", devices=devices or {})


class ExecuteSubgraphTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.run_repo = RunRepository(self.db)
        self.runner = StepRunner(self.db)
        self.run = _make_run(self.db)

    async def test_linear_child_branch_no_persistence(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("a", "run-command"),
            _node("b", "run-command"),
        ]
        edges = [_edge("inv", "a"), _edge("a", "b")]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        initial = _ctx({"d1": _device("d1"), "d2": _device("d2")})
        called: list[str] = []

        async def _stub(**kwargs: Any) -> list[StepOutcome]:
            called.append(kwargs["node_id"])
            return [StepOutcome(name="success", context=kwargs["context"])]

        with patch.object(StepRunner, "_execute_step", side_effect=_stub):
            step_outcomes, step_errors = await self.runner.execute_subgraph(
                run=self.run,
                workflow=wf,
                initial_context=initial,
                inventory_node_id="inv",
                allowed_node_ids={"a", "b"},
            )

        self.assertEqual(called, ["a", "b"])
        self.assertEqual(step_errors, {})
        self.assertEqual(set(step_outcomes), {"inv", "a", "b"})
        self.assertEqual(set(step_outcomes["a"]["success"].devices), {"d1", "d2"})
        # Subgraph must NOT write WorkflowStepResult rows (parent persists).
        self.assertEqual(self.run_repo.get_step_results_for_run(self.run.id), [])

    async def test_child_node_raise_is_recorded_and_blocks_downstream(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("a", "run-command"),
            _node("b", "run-command"),
        ]
        edges = [_edge("inv", "a"), _edge("a", "b")]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        initial = _ctx({"d1": _device("d1")})
        called: list[str] = []

        async def _stub(**kwargs: Any) -> list[StepOutcome]:
            called.append(kwargs["node_id"])
            if kwargs["node_id"] == "a":
                raise RuntimeError("boom")
            return [StepOutcome(name="success", context=kwargs["context"])]

        with patch.object(StepRunner, "_execute_step", side_effect=_stub):
            step_outcomes, step_errors = await self.runner.execute_subgraph(
                run=self.run,
                workflow=wf,
                initial_context=initial,
                inventory_node_id="inv",
                allowed_node_ids={"a", "b"},
            )

        self.assertEqual(called, ["a"])  # "b" blocked by upstream failure
        self.assertIn("a", step_errors)
        self.assertEqual(step_errors["a"]["message"], "boom")
        self.assertEqual(step_errors["a"]["category"], "execution")
        self.assertTrue(step_errors["a"]["error_id"])
        self.assertIn("failure", step_outcomes["a"])


class ResumeAfterJoinTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.run_repo = RunRepository(self.db)
        self.runner = StepRunner(self.db)
        self.run = _make_run(self.db)

    def _statuses(self) -> dict[str, str]:
        return {
            r.step_node_id: r.status
            for r in self.run_repo.get_step_results_for_run(self.run.id)
        }

    async def test_join_and_downstream_run_once_and_persist(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("join", "fan-in"),
            _node("store", "store-artifact"),
        ]
        edges = [_edge("inv", "join"), _edge("join", "store")]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        merged = {"inv": {"success": _ctx({"d1": _device("d1"), "d2": _device("d2")})}}
        called: list[str] = []

        async def _stub(**kwargs: Any) -> list[StepOutcome]:
            called.append(kwargs["node_id"])
            return [StepOutcome(name="success", context=kwargs["context"])]

        with patch.object(StepRunner, "_execute_step", side_effect=_stub):
            ok = await self.runner.resume_after_join(
                run=self.run,
                workflow=wf,
                merged_outcomes=merged,
                join_node_id="join",
            )

        self.assertTrue(ok)
        self.assertEqual(called, ["join", "store"])
        self.assertEqual(self._statuses(), {"join": "success", "store": "success"})

    async def test_raise_in_post_join_node_fails_and_skips_rest(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("join", "fan-in"),
            _node("store", "store-artifact"),
            _node("notify", "show-summary"),
        ]
        edges = [_edge("inv", "join"), _edge("join", "store"), _edge("store", "notify")]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        merged = {"inv": {"success": _ctx({"d1": _device("d1")})}}
        called: list[str] = []

        async def _stub(**kwargs: Any) -> list[StepOutcome]:
            called.append(kwargs["node_id"])
            if kwargs["node_id"] == "store":
                raise RuntimeError("store failed")
            return [StepOutcome(name="success", context=kwargs["context"])]

        with patch.object(StepRunner, "_execute_step", side_effect=_stub):
            ok = await self.runner.resume_after_join(
                run=self.run,
                workflow=wf,
                merged_outcomes=merged,
                join_node_id="join",
            )

        self.assertFalse(ok)
        self.assertEqual(called, ["join", "store"])
        self.assertEqual(
            self._statuses(),
            {"join": "success", "store": "failed", "notify": "skipped"},
        )


@contextmanager
def _keep_open(db: Session) -> Any:
    """A SessionLocal() substitute that hands back the test's live session
    without closing it on __exit__."""
    yield db


class _NullWorkflowRepo:
    """Constructible stand-in for WorkflowRepository; get_by_id unused when
    signal.join_node_id is None."""

    def __init__(self, _db: Any) -> None: ...

    def get_by_id(self, _wid: Any) -> Any:  # pragma: no cover - not reached
        raise AssertionError("get_by_id should not be called without a join node")


class FinalizeFanOutParentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.run_repo = RunRepository(self.db)
        self.run = _make_run(self.db)

    def _statuses(self) -> dict[str, str]:
        return {
            r.step_node_id: r.status
            for r in self.run_repo.get_step_results_for_run(self.run.id)
        }

    def _session_local(self) -> Any:
        return lambda: _keep_open(self.db)

    async def test_no_join_aggregates_child_outcomes(self) -> None:
        for nid in ("a", "b"):
            self.run_repo.create_step_result(
                run_id=self.run.id, step_node_id=nid, step_type="run-command", step_name=nid
            )
        canvas_nodes = [{"id": "inv"}, {"id": "a"}, {"id": "b"}]
        canvas_edges = [{"source": "inv", "target": "a"}, {"source": "inv", "target": "b"}]
        ctx_dump = _ctx({"d1": _device("d1")}).model_dump(mode="json")
        signal = FanOutSignal(
            inventory_node_id="inv",
            fan_out_config={"enabled": True, "mode": "per_device"},
            inventory_outcome=_ctx({"d1": _device("d1")}),
            join_node_id=None,
        )
        child_results = [
            {"execute_device_group": {"a": {"success": ctx_dump}, "b": {"success": ctx_dump}}}
        ]

        status = await _finalize_fan_out_parent(
            run_id=self.run.id,
            signal=signal,
            canvas_nodes=canvas_nodes,
            canvas_edges=canvas_edges,
            child_results=child_results,
            SessionLocal=self._session_local(),
            RunRepository=RunRepository,
            WorkflowRepository=_NullWorkflowRepo,
            StepRunner=StepRunner,
        )

        self.assertEqual(status, "success")
        self.assertEqual(self._statuses(), {"a": "success", "b": "success"})
        run, _ = self.run_repo.get_run_by_id(self.run.id)
        self.assertEqual(run.status, "success")

    async def test_with_join_resumes_after_join(self) -> None:
        for nid in ("cmd", "join", "store"):
            self.run_repo.create_step_result(
                run_id=self.run.id, step_node_id=nid, step_type="run-command", step_name=nid
            )
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("cmd", "run-command"),
            _node("join", "fan-in"),
            _node("store", "store-artifact"),
        ]
        edges = [_edge("inv", "cmd"), _edge("cmd", "join"), _edge("join", "store")]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)

        class _FakeWorkflowRepo:
            def __init__(self, _db: Any) -> None: ...

            def get_by_id(self, _wid: Any) -> Any:
                return (wf, None)

        ctx_dump = _ctx({"d1": _device("d1")}).model_dump(mode="json")
        signal = FanOutSignal(
            inventory_node_id="inv",
            fan_out_config={"enabled": True, "mode": "per_device"},
            inventory_outcome=_ctx({"d1": _device("d1")}),
            join_node_id="join",
        )
        child_results = [{"execute_device_group": {"cmd": {"success": ctx_dump}}}]
        called: list[str] = []

        async def _stub(**kwargs: Any) -> list[StepOutcome]:
            called.append(kwargs["node_id"])
            return [StepOutcome(name="success", context=kwargs["context"])]

        with patch.object(StepRunner, "_execute_step", side_effect=_stub):
            status = await _finalize_fan_out_parent(
                run_id=self.run.id,
                signal=signal,
                canvas_nodes=nodes,
                canvas_edges=edges,
                child_results=child_results,
                SessionLocal=self._session_local(),
                RunRepository=RunRepository,
                WorkflowRepository=_FakeWorkflowRepo,
                StepRunner=StepRunner,
            )

        self.assertEqual(status, "success")
        self.assertEqual(called, ["join", "store"])
        statuses = self._statuses()
        self.assertEqual(statuses["cmd"], "success")
        self.assertEqual(statuses["join"], "success")
        self.assertEqual(statuses["store"], "success")


class FanOutSignalPayloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.run_repo = RunRepository(self.db)
        self.runner = StepRunner(self.db)

    async def test_fan_out_signal_shape_from_phase1_walk(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("join", "fan-in"),
            _node("store", "store-artifact"),
        ]
        edges = [_edge("inv", "join"), _edge("join", "store")]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        run = _make_run(self.db)
        ctx = AsyncMock()

        async def _stub(**kwargs: Any) -> list[StepOutcome]:
            out = kwargs["context"].model_copy(
                update={
                    "devices": {"d1": _device("d1")},
                    "metadata": {"_fan_out": {"enabled": True, "mode": "per_device"}},
                }
            )
            return [StepOutcome(name="success", context=out)]

        with patch.object(StepRunner, "_execute_step", side_effect=_stub):
            final_status, fan_out, _ = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=wf, ctx=ctx
            )

        self.assertIsNone(final_status)
        self.assertIsNotNone(fan_out)
        signal = fan_out["signal"]
        self.assertIsInstance(signal, FanOutSignal)
        self.assertEqual(signal.inventory_node_id, "inv")
        self.assertEqual(signal.join_node_id, "join")
        self.assertEqual(signal.fan_out_config.get("mode"), "per_device")


if __name__ == "__main__":
    unittest.main()
