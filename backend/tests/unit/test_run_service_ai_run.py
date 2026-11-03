"""RunService.trigger_ai_run: a confirmed assistant start, only for a still-released workflow."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.domain_exceptions import AccessDeniedError, NotFoundError, ValidationFailedError
from core.models.background_tier import WorkflowBackgroundTier
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from services.execution.run_service import RunService

ATTRS = [{"name": "features", "type": "string", "default": None, "required": True}]


class TriggerAiRunTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Workflow.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
                WorkflowBackgroundTier.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.service = RunService(self.db)
        patcher = patch(
            "hatchet.workflows.workflow_run.workflow.run_no_wait",
            return_value=MagicMock(workflow_run_id="h-1"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _workflow(self, **kw) -> Workflow:
        values = {
            "name": "wf",
            "creator_id": 1,
            "visibility": "public",
            "static_attributes": ATTRS,
            "ai_released": True,
        }
        wf = Workflow(**{**values, **kw})
        self.db.add(wf)
        self.db.commit()
        return wf

    def _start(self, wf: Workflow, user_id: int = 2, inputs: dict | None = None):
        return self.service.trigger_ai_run(
            wf.id,
            user_id,
            run_inputs=inputs if inputs is not None else {"features": "ospf"},
            device_ids=["d1"],
        )

    def test_starts_as_the_confirming_user_with_the_assistant_trigger(self) -> None:
        run = self._start(self._workflow())
        row = self.db.get(WorkflowRun, run.id)
        self.assertEqual(row.trigger_type, "ai_assistant")
        self.assertEqual(row.triggered_by_id, 2)
        self.assertEqual(row.run_inputs, {"features": "ospf"})
        self.assertEqual(row.device_ids, ["d1"])

    def test_refuses_a_workflow_that_is_no_longer_released(self) -> None:
        wf = self._workflow(ai_released=False)
        with self.assertRaises(ValidationFailedError):
            self._start(wf)
        self.assertEqual(self.db.query(WorkflowRun).count(), 0)

    def test_still_validates_the_inputs(self) -> None:
        with self.assertRaises(ValidationFailedError):
            self._start(self._workflow(), inputs={"unknown": 1})

    def test_private_workflow_of_someone_else_is_refused(self) -> None:
        wf = self._workflow(visibility="private", creator_id=1)
        with self.assertRaises(AccessDeniedError):
            self._start(wf, user_id=2)

    def test_missing_workflow(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.trigger_ai_run(999, 1, run_inputs={}, device_ids=[])


if __name__ == "__main__":
    unittest.main()
