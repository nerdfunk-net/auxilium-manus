"""Tests for concurrent execution of independent canvas branches.

`StepRunner.execute_all`/`resume_after_join` walk topological *generations*
(`services.execution.graph.topological_generations`) instead of a flat
node-at-a-time list — siblings with no dependency on one another now run
concurrently via `asyncio.gather` inside `StepRunner._run_wave`. See
doc/plans/PARALLEL_EXEC.md and doc/HOWTO_BUILD_WORKFLOWS.md "independent
branches run concurrently".

Exercised through `_run_steps_until_fan_out_or_done`, the real production
entry point, using the same harness as `test_step_runner_blocked_by_failure.py`.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from hatchet.workflows.workflow_run import _run_steps_until_fan_out_or_done
from models.workflow_context import DeviceContext, DeviceError, StepOutcome, WorkflowContext
from repositories.run_repository import RunRepository
from services.execution.step_runner import StepRunner


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
        device_ids=[],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _device(device_id: str) -> DeviceContext:
    return DeviceContext(id=device_id, name=device_id, hostname=device_id)


def _mark_failed(device: DeviceContext, node_id: str) -> DeviceContext:
    error = DeviceError(node_id=node_id, step_id="run-command", code="boom", message="boom")
    return device.model_copy(update={"errors": [error]})


def _success_with_devices(
    context: WorkflowContext, devices: dict[str, DeviceContext]
) -> list[StepOutcome]:
    return [StepOutcome(name="success", context=context.model_copy(update={"devices": devices}))]


def _fail_all_devices_outcomes(node_id: str, context: WorkflowContext) -> list[StepOutcome]:
    failed = {did: _mark_failed(dc, node_id) for did, dc in context.devices.items()}
    return [
        StepOutcome(name="success", context=context.model_copy(update={"devices": {}})),
        StepOutcome(name="failure", context=context.model_copy(update={"devices": failed})),
    ]


class ParallelExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.run_repo = RunRepository(self.db)
        self.runner = StepRunner(self.db)

    def _step_results_for(self, run_id: int) -> dict[str, WorkflowStepResult]:
        return {r.step_node_id: r for r in self.run_repo.get_step_results_for_run(run_id)}

    async def test_three_way_fan_in_runs_concurrently_and_merges_distinct_keys(self) -> None:
        """configs -> {parse_cisco, batfish, pyats} -> fan_in — the three
        analysis branches have no dependency on each other. Proves they
        actually overlap in time (not just "all eventually ran") and that
        the fan-in merge collects all three distinct `parsed[output_key]`
        entries."""
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("configs", "run-command"),
            _node("parse_cisco", "run-command"),
            _node("batfish", "run-command"),
            _node("pyats", "run-command"),
            _node("fan_in", "run-command"),
        ]
        edges = [
            _edge("inv", "configs"),
            _edge("configs", "parse_cisco"),
            _edge("configs", "batfish"),
            _edge("configs", "pyats"),
            _edge("parse_cisco", "fan_in"),
            _edge("batfish", "fan_in"),
            _edge("pyats", "fan_in"),
        ]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        run = _make_run(self.db)
        ctx = AsyncMock()

        output_key_by_node = {
            "parse_cisco": "cisco_parsed",
            "batfish": "batfish_facts",
            "pyats": "pyats_snapshot",
        }
        in_flight = 0
        max_in_flight = 0
        fan_in_context: WorkflowContext | None = None

        async def _execute_step_stub(**kwargs: Any) -> list[StepOutcome]:
            nonlocal in_flight, max_in_flight, fan_in_context
            node_id = kwargs["node_id"]
            context: WorkflowContext = kwargs["context"]

            if node_id == "inv":
                devices = {"d1": _device("d1")}
                return _success_with_devices(context, devices)
            if node_id == "configs":
                return [StepOutcome(name="success", context=context)]
            if node_id in output_key_by_node:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
                await asyncio.sleep(0)  # yield so siblings actually interleave
                output_key = output_key_by_node[node_id]
                updated_devices = {
                    did: dc.model_copy(
                        update={"parsed": {**dc.parsed, output_key: {"from": node_id}}}
                    )
                    for did, dc in context.devices.items()
                }
                in_flight -= 1
                return _success_with_devices(context, updated_devices)
            if node_id == "fan_in":
                fan_in_context = context
                return [StepOutcome(name="success", context=context)]
            raise AssertionError(f"unexpected node {node_id!r}")

        with patch.object(StepRunner, "_execute_step", side_effect=_execute_step_stub):
            final_status, fan_out, _ = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=wf, ctx=ctx
            )

        self.assertIsNone(fan_out)
        self.assertEqual(final_status, "success")
        self.assertGreaterEqual(max_in_flight, 2, "siblings never overlapped — still sequential")

        assert fan_in_context is not None
        merged_parsed = fan_in_context.devices["d1"].parsed
        self.assertEqual(
            set(merged_parsed),
            {"cisco_parsed", "batfish_facts", "pyats_snapshot"},
        )

    async def test_merge_conflict_on_duplicate_output_key_fails_the_run(self) -> None:
        """Two parallel branches that reuse the same output_key with
        different data must not be silently merged — the existing
        `_merge_shallow_dicts` conflict guard must still fire under
        concurrency."""
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("branch_a", "run-command"),
            _node("branch_b", "run-command"),
            _node("fan_in", "run-command"),
        ]
        edges = [
            _edge("inv", "branch_a"),
            _edge("inv", "branch_b"),
            _edge("branch_a", "fan_in"),
            _edge("branch_b", "fan_in"),
        ]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        run = _make_run(self.db)
        ctx = AsyncMock()

        async def _execute_step_stub(**kwargs: Any) -> list[StepOutcome]:
            node_id = kwargs["node_id"]
            context: WorkflowContext = kwargs["context"]

            if node_id == "inv":
                devices = {"d1": _device("d1")}
                return _success_with_devices(context, devices)
            if node_id in ("branch_a", "branch_b"):
                updated_devices = {
                    did: dc.model_copy(update={"parsed": {"shared_key": {"from": node_id}}})
                    for did, dc in context.devices.items()
                }
                return _success_with_devices(context, updated_devices)
            if node_id == "fan_in":
                raise AssertionError("fan_in should never run — merging its input must raise")
            raise AssertionError(f"unexpected node {node_id!r}")

        with patch.object(StepRunner, "_execute_step", side_effect=_execute_step_stub):
            final_status, fan_out, _ = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=wf, ctx=ctx
            )

        self.assertIsNone(fan_out)
        self.assertEqual(final_status, "failed")

        results = self._step_results_for(run.id)
        self.assertEqual(results["fan_in"].status, "failed")
        self.assertEqual(results["fan_in"].error_category, "configuration")

    async def test_sibling_survives_when_other_sibling_raises(self) -> None:
        """A genuine engine-level exception in one wave sibling (simulated
        via a failing persistence write, since step-level exceptions are
        already caught inside `_execute_and_persist_node`) must not strand
        or cancel the other, already-in-flight sibling — and must still
        propagate once the wave finishes."""
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("b1", "run-command"),
            _node("b2", "run-command"),
        ]
        edges = [_edge("inv", "b1"), _edge("inv", "b2")]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        run = _make_run(self.db)
        ctx = AsyncMock()

        b1_ran = False

        async def _execute_step_stub(**kwargs: Any) -> list[StepOutcome]:
            nonlocal b1_ran
            node_id = kwargs["node_id"]
            context: WorkflowContext = kwargs["context"]
            if node_id == "inv":
                devices = {"d1": _device("d1")}
                return _success_with_devices(context, devices)
            if node_id == "b1":
                await asyncio.sleep(0.01)  # let b2 raise first
                b1_ran = True
                return [StepOutcome(name="success", context=context)]
            if node_id == "b2":
                return [StepOutcome(name="success", context=context)]
            raise AssertionError(f"unexpected node {node_id!r}")

        real_update = self.runner.repo.update_step_result

        def _maybe_boom(step_result: WorkflowStepResult, **fields: Any) -> WorkflowStepResult:
            if step_result.step_node_id == "b2" and fields.get("status") == "running":
                raise RuntimeError("simulated infra failure")
            return real_update(step_result, **fields)

        with (
            patch.object(StepRunner, "_execute_step", side_effect=_execute_step_stub),
            patch.object(self.runner.repo, "update_step_result", side_effect=_maybe_boom),
        ):
            with self.assertRaises(RuntimeError):
                await _run_steps_until_fan_out_or_done(
                    run_repo=self.run_repo, runner=self.runner, run=run, wf=wf, ctx=ctx
                )

        self.assertTrue(b1_ran, "b1 was stranded/cancelled when its sibling b2 raised")

    async def test_blocked_by_upstream_failure_reads_concurrent_wave_results(self) -> None:
        """Two independent failing branches fan into one shared sink (the
        notify-on-error pattern) — same shape as
        test_shared_sink_receives_union_of_two_failing_branches_once in
        test_step_runner_blocked_by_failure.py, but here the two failing
        branches genuinely overlap in time, confirming
        `_blocked_by_upstream_failure` still reads correctly off
        wave-produced step_outcomes."""
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("fails_a", "run-command"),
            _node("fails_b", "run-command"),
            _node("sink", "run-command"),
        ]
        edges = [
            _edge("inv", "fails_a"),
            _edge("inv", "fails_b"),
            _edge("fails_a", "sink", source_handle="failure"),
            _edge("fails_b", "sink", source_handle="failure"),
        ]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        run = _make_run(self.db)
        ctx = AsyncMock()
        in_flight = 0
        max_in_flight = 0
        sink_devices: dict[str, DeviceContext] = {}

        async def _execute_step_stub(**kwargs: Any) -> list[StepOutcome]:
            nonlocal in_flight, max_in_flight
            node_id = kwargs["node_id"]
            context: WorkflowContext = kwargs["context"]
            if node_id == "inv":
                devices = {"d1": _device("d1"), "d2": _device("d2")}
                return _success_with_devices(context, devices)
            if node_id in ("fails_a", "fails_b"):
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
                await asyncio.sleep(0)
                in_flight -= 1
                return _fail_all_devices_outcomes(node_id, context)
            if node_id == "sink":
                sink_devices.update(context.devices)
                return [StepOutcome(name="success", context=context)]
            raise AssertionError(f"unexpected node {node_id!r}")

        with patch.object(StepRunner, "_execute_step", side_effect=_execute_step_stub):
            final_status, fan_out, _ = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=wf, ctx=ctx
            )

        self.assertIsNone(fan_out)
        self.assertGreaterEqual(
            max_in_flight, 2, "fails_a/fails_b never overlapped — still sequential"
        )
        self.assertEqual(final_status, "failed")
        self.assertEqual(set(sink_devices), {"d1", "d2"})


if __name__ == "__main__":
    unittest.main()
