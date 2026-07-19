"""Tests for the ``final`` keyword on ``_aggregate_and_persist``.

``final=False`` is used by Wait & Run to make finished batches inspectable
while later batches are still gated on approval -- see doc/WAIT-AND-RUN.md §6.4.
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from hatchet.workflows.workflow_run import _aggregate_and_persist
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from repositories.run_repository import RunRepository
from services.execution.step_runner import FanOutSignal

CANVAS_NODES = [{"id": "inv"}, {"id": "a"}, {"id": "b"}]
CANVAS_EDGES = [{"source": "inv", "target": "a"}, {"source": "inv", "target": "b"}]


def _device(did: str) -> DeviceContext:
    return DeviceContext(
        id=did,
        name=did,
        hostname=did,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


class AggregateAndPersistFinalTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine, tables=[User.__table__, WorkflowRun.__table__, WorkflowStepResult.__table__]
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.run_repo = RunRepository(self.db)

        self.run = WorkflowRun(
            uuid="run-uuid-1",
            workflow_id=1,
            triggered_by_id=None,
            status="running",
            trigger_type="manual",
            run_mode="normal",
            device_ids=[],
        )
        self.db.add(self.run)
        self.db.commit()
        self.db.refresh(self.run)

        # Only "a" and "b" are child-branch nodes; both start pending, as
        # StepRunner.create_pending_step_results would leave them at the start
        # of a real run.
        self.result_a = self.run_repo.create_step_result(
            run_id=self.run.id, step_node_id="a", step_type="run-command", step_name="a"
        )
        self.result_b = self.run_repo.create_step_result(
            run_id=self.run.id, step_node_id="b", step_type="run-command", step_name="b"
        )

        devices = {"d0": _device("d0")}
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices)
        self.signal = FanOutSignal(
            inventory_node_id="inv",
            fan_out_config={"enabled": True, "mode": "per_device"},
            inventory_outcome=context,
            join_node_id=None,
        )

        # A single child reported an outcome for "a" only -- "b" never ran
        # (simulating a batch where only some child-branch nodes were reached).
        child_ctx = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices)
        self.child_results = [
            {"execute_device_group": {"a": {"success": child_ctx.model_dump(mode="json")}}}
        ]

    def _status_for(self, node_id: str) -> str:
        results = {r.step_node_id: r for r in self.run_repo.get_step_results_for_run(self.run.id)}
        return results[node_id].status

    def test_final_false_leaves_untouched_node_pending(self) -> None:
        success, merged = _aggregate_and_persist(
            run_repo=self.run_repo,
            run_id=self.run.id,
            signal=self.signal,
            canvas_nodes=CANVAS_NODES,
            canvas_edges=CANVAS_EDGES,
            child_results=self.child_results,
            final=False,
        )

        self.assertTrue(success)
        self.assertIn("a", merged)
        self.assertNotIn("b", merged)
        self.assertEqual(self._status_for("a"), "success")
        self.assertEqual(self._status_for("b"), "pending")

    def test_final_true_marks_untouched_node_skipped(self) -> None:
        _aggregate_and_persist(
            run_repo=self.run_repo,
            run_id=self.run.id,
            signal=self.signal,
            canvas_nodes=CANVAS_NODES,
            canvas_edges=CANVAS_EDGES,
            child_results=self.child_results,
            final=True,
        )

        self.assertEqual(self._status_for("a"), "success")
        self.assertEqual(self._status_for("b"), "skipped")

    def test_default_is_final_true(self) -> None:
        _aggregate_and_persist(
            run_repo=self.run_repo,
            run_id=self.run.id,
            signal=self.signal,
            canvas_nodes=CANVAS_NODES,
            canvas_edges=CANVAS_EDGES,
            child_results=self.child_results,
        )

        self.assertEqual(self._status_for("b"), "skipped")


if __name__ == "__main__":
    unittest.main()
