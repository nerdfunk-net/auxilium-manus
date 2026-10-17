"""Tests for static-attribute (run_inputs) validation on RunService.trigger_run.

See doc/WORKFLOW-STEPS.md "Static attributes" — values declared on a
Workflow's static_attributes schema must be validated/defaulted before a
manual trigger creates a WorkflowRun and dispatches it to Hatchet.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.domain_exceptions import ValidationFailedError
from core.models.background_tier import WorkflowBackgroundTier
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from models.runs import WorkflowRunCreate
from services.execution.run_service import RunService

USER_ID = 1

STATIC_ATTRIBUTES = [
    {"name": "vlan_id", "type": "number", "default": None, "required": True},
    {"name": "note", "type": "string", "default": "n/a", "required": False},
    {"name": "confirm", "type": "boolean", "default": False, "required": False},
]


class RunServiceRunInputsTests(unittest.TestCase):
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

        fake_ref = MagicMock(workflow_run_id="hatchet-run-1")
        run_no_wait_patch = patch(
            "hatchet.workflows.workflow_run.workflow.run_no_wait", return_value=fake_ref
        )
        self.mock_run_no_wait = run_no_wait_patch.start()
        self.addCleanup(run_no_wait_patch.stop)

    def _make_workflow(self, static_attributes: list[dict] | None) -> Workflow:
        workflow = Workflow(
            name="wf-1",
            creator_id=USER_ID,
            visibility="public",
            static_attributes=static_attributes,
        )
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def test_trigger_run_400_when_required_attribute_missing(self) -> None:
        workflow = self._make_workflow(STATIC_ATTRIBUTES)

        with self.assertRaises(ValidationFailedError) as ctx:
            self.service.trigger_run(
                workflow_id=workflow.id, data=WorkflowRunCreate(), user_id=USER_ID
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("vlan_id", ctx.exception.detail)
        self.mock_run_no_wait.assert_not_called()

    def test_trigger_run_400_on_unknown_run_input_key(self) -> None:
        workflow = self._make_workflow(STATIC_ATTRIBUTES)

        with self.assertRaises(ValidationFailedError) as ctx:
            self.service.trigger_run(
                workflow_id=workflow.id,
                data=WorkflowRunCreate(run_inputs={"vlan_id": 100, "bogus": "x"}),
                user_id=USER_ID,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("bogus", ctx.exception.detail)

    def test_trigger_run_fills_defaults_and_persists_run_inputs(self) -> None:
        workflow = self._make_workflow(STATIC_ATTRIBUTES)

        response = self.service.trigger_run(
            workflow_id=workflow.id,
            data=WorkflowRunCreate(run_inputs={"vlan_id": 100, "confirm": True}),
            user_id=USER_ID,
        )

        self.assertEqual(
            response.run_inputs, {"vlan_id": 100, "note": "n/a", "confirm": True}
        )
        self.mock_run_no_wait.assert_called_once()

    def test_trigger_run_with_no_static_attributes_ignores_empty_run_inputs(self) -> None:
        workflow = self._make_workflow(None)

        response = self.service.trigger_run(
            workflow_id=workflow.id, data=WorkflowRunCreate(), user_id=USER_ID
        )

        self.assertEqual(response.run_inputs, {})
        self.mock_run_no_wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
