"""StepRunner binds a RunEventContext around every node it executes."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.runs import WorkflowRun, WorkflowRunDeviceGroup, WorkflowStepResult
from core.models.users import User
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.execution.run_events_reporter import RunEventContext, current_run_event_context
from services.execution.step_runner import StepRunner


def _node(node_id: str) -> dict[str, Any]:
    return {"id": node_id, "data": {"kind": "run-command", "title": node_id}}


class StepRunnerEventContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
                WorkflowRunDeviceGroup.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        run = WorkflowRun(
            uuid="run-uuid-1",
            workflow_id=1,
            triggered_by_id=None,
            status="running",
            trigger_type="manual",
            device_ids=[],
        )
        self.db.add(run)
        self.db.commit()
        self.run = run
        self.runner = StepRunner(self.db)
        self.seen: dict[str, RunEventContext | None] = {}

    async def _stub(self, **kwargs: Any) -> list[StepOutcome]:
        self.seen[kwargs["node_id"]] = current_run_event_context()
        return [StepOutcome(name="success", context=kwargs["context"])]

    async def test_execute_all_binds_run_and_node_without_child_index(self) -> None:
        wf = SimpleNamespace(
            id=1,
            canvas_nodes=[_node("a"), _node("b")],
            canvas_edges=[{"source": "a", "target": "b"}],
        )

        with patch.object(StepRunner, "_execute_step", side_effect=self._stub):
            await self.runner.execute_all(run=self.run, workflow=wf)

        self.assertEqual(self.seen["a"], RunEventContext(run_id=self.run.id, node_id="a"))
        self.assertEqual(self.seen["b"], RunEventContext(run_id=self.run.id, node_id="b"))
        self.assertIsNone(current_run_event_context())

    async def test_subgraph_binds_child_index(self) -> None:
        wf = SimpleNamespace(
            id=1,
            canvas_nodes=[_node("inv"), _node("a")],
            canvas_edges=[{"source": "inv", "target": "a"}],
        )
        ctx = WorkflowContext(
            run_id="r",
            workflow_id="1",
            devices={"d": DeviceContext(id="d", name="d", hostname="d")},
        )

        with patch.object(StepRunner, "_execute_step", side_effect=self._stub):
            await self.runner.execute_subgraph(
                run=self.run,
                workflow=wf,
                initial_context=ctx,
                inventory_node_id="inv",
                allowed_node_ids={"a"},
                child_index=5,
            )

        self.assertEqual(
            self.seen["a"], RunEventContext(run_id=self.run.id, node_id="a", child_index=5)
        )
        self.assertIsNone(current_run_event_context())

    async def test_context_is_reset_when_the_executor_raises(self) -> None:
        wf = SimpleNamespace(id=1, canvas_nodes=[_node("a")], canvas_edges=[])

        async def boom(**kwargs: Any) -> list[StepOutcome]:
            raise RuntimeError("device unreachable")

        with patch.object(StepRunner, "_execute_step", side_effect=boom):
            await self.runner.execute_all(run=self.run, workflow=wf)

        self.assertIsNone(current_run_event_context())


if __name__ == "__main__":
    unittest.main()
