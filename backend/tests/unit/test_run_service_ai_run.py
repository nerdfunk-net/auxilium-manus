"""RunService.trigger_ai_run: a confirmed assistant start, only for a still-current release."""

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
from services.execution.run_service import AiReleaseNotCurrentError, RunService
from services.workflow.release_stamp import compute_stamp, release_is_current, release_settings

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

    def _load(self, workflow_id: int) -> Workflow | None:
        return self.db.get(Workflow, workflow_id)

    def _workflow(self, *, released: bool = True, **kw) -> Workflow:
        values = {
            "name": "wf",
            "creator_id": 1,
            "visibility": "public",
            "static_attributes": ATTRS,
            "ai_released": released,
            "ai_description": "d",
            "ai_result_node_id": "cmp",
        }
        wf = Workflow(**{**values, **kw})
        self.db.add(wf)
        self.db.commit()
        if released:
            self.restamp(wf)
        return wf

    def restamp(self, wf: Workflow) -> str:
        wf.ai_release_stamp = compute_stamp(wf, release_settings(wf), self._load)
        self.db.commit()
        return wf.ai_release_stamp

    def _start(self, wf: Workflow, user_id: int = 2, inputs: dict | None = None, stamp=None):
        return self.service.trigger_ai_run(
            wf.id,
            user_id,
            run_inputs=inputs if inputs is not None else {"features": "ospf"},
            expected_stamp=wf.ai_release_stamp if stamp is None else stamp,
        )

    def test_starts_as_the_confirming_user_with_the_assistant_trigger(self) -> None:
        run = self._start(self._workflow())
        row = self.db.get(WorkflowRun, run.id)
        self.assertEqual(row.trigger_type, "ai_assistant")
        self.assertEqual(row.triggered_by_id, 2)
        self.assertEqual(row.run_inputs, {"features": "ospf"})

    def test_the_designated_result_step_is_stored_on_the_run(self) -> None:
        wf = self._workflow()
        run = self._start(wf)
        self.assertEqual(self.db.get(WorkflowRun, run.id).ai_result_node_id, "cmp")
        self.assertEqual(run.ai_result_node_id, "cmp")

    def test_a_later_release_does_not_move_the_result_of_an_older_run(self) -> None:
        wf = self._workflow()
        run = self._start(wf)
        wf.ai_result_node_id = "other"
        self.restamp(wf)
        self.assertEqual(self.db.get(WorkflowRun, run.id).ai_result_node_id, "cmp")

    def test_refuses_a_workflow_that_is_not_released(self) -> None:
        wf = self._workflow(released=False)
        with self.assertRaises(AiReleaseNotCurrentError):
            self._start(wf, stamp="x")
        self.assertEqual(self.db.query(WorkflowRun).count(), 0)

    def test_a_release_without_a_stamp_is_not_a_release(self) -> None:
        wf = self._workflow()
        wf.ai_release_stamp = None
        self.db.commit()
        with self.assertRaises(AiReleaseNotCurrentError):
            self._start(wf, stamp="x")

    def test_a_save_that_raced_the_release_cannot_start(self) -> None:
        """The flag stayed true on a canvas nobody released: the stamp no longer matches."""
        wf = self._workflow()
        stamp = wf.ai_release_stamp
        wf.canvas_nodes = [{"id": "new-step"}]
        self.db.commit()
        with self.assertRaises(AiReleaseNotCurrentError):
            self._start(wf, stamp=stamp)
        self.assertEqual(self.db.query(WorkflowRun).count(), 0)

    def test_editing_a_workflow_it_starts_ends_the_release(self) -> None:
        child = self._workflow(released=False, name="child")
        step = {
            "id": "s",
            "data": {"kind": "start-workflow", "pluginConfig": {"workflow_id": child.id}},
        }
        parent = self._workflow(name="parent", canvas_nodes=[step])
        self.assertTrue(release_is_current(parent, self._load))  # as reviewed

        child.canvas_nodes = [{"id": "changed"}]
        self.db.commit()
        with self.assertRaises(AiReleaseNotCurrentError):
            self._start(parent)

    def test_a_proposal_from_before_a_re_release_is_refused(self) -> None:
        wf = self._workflow()
        old = wf.ai_release_stamp
        wf.ai_description = "released again with other words"
        self.restamp(wf)
        with self.assertRaisesRegex(AiReleaseNotCurrentError, "Ask the assistant again"):
            self._start(wf, stamp=old)
        self.assertEqual(self.db.query(WorkflowRun).count(), 0)

    def test_still_validates_the_inputs(self) -> None:
        with self.assertRaises(ValidationFailedError):
            self._start(self._workflow(), inputs={"unknown": 1})

    def test_a_reference_the_user_cannot_use_is_refused(self) -> None:
        from services.execution.reference_resolver import ReferenceValidationError

        wf = self._workflow()
        with patch(
            "services.execution.run_service.validate_reference_inputs",
            side_effect=ReferenceValidationError("cred: no credential named 'x' is visible to you"),
        ):
            with self.assertRaises(ValidationFailedError):
                self._start(wf)
        self.assertEqual(self.db.query(WorkflowRun).count(), 0)

    def test_private_workflow_of_someone_else_is_refused(self) -> None:
        wf = self._workflow(visibility="private", creator_id=1)
        with self.assertRaises(AccessDeniedError):
            self._start(wf, user_id=2)

    def test_missing_workflow(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.trigger_ai_run(999, 1, run_inputs={}, expected_stamp="x")


if __name__ == "__main__":
    unittest.main()
