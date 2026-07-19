"""Tests for the Wait & Run approval endpoints on RunService.

Covers the mutual-exclusion guards between debug-mode stepping
(step_run/continue_run) and batch approval (approve_batch/approve_all) --
see doc/WAIT-AND-RUN.md §7.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from services.execution.run_events import batch_approval_event_key, debug_step_event_key
from services.execution.run_service import RunService

USER_ID = 1


class RunServiceApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Workflow.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)

        workflow = Workflow(name="wf-1", creator_id=USER_ID, visibility="public")
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        self.workflow = workflow

        self.service = RunService(self.db)

        hatchet_patch = patch("hatchet.client.hatchet", new=MagicMock())
        self.mock_hatchet = hatchet_patch.start()
        self.addCleanup(hatchet_patch.stop)

    def _make_run(self, **overrides) -> WorkflowRun:
        defaults = dict(
            uuid="run-uuid-1",
            workflow_id=self.workflow.id,
            triggered_by_id=None,
            status="running",
            trigger_type="manual",
            run_mode="normal",
            device_ids=[],
        )
        defaults.update(overrides)
        run = WorkflowRun(**defaults)
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    # ─── approve_batch / approve_all guards ─────────────────────────────────

    def test_approve_batch_409_when_run_not_paused(self) -> None:
        run = self._make_run(status="running")

        with self.assertRaises(HTTPException) as ctx:
            self.service.approve_batch(run_id=run.id, user_id=USER_ID)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_approve_batch_409_when_not_awaiting_approval(self) -> None:
        # A debug-mode pause: paused + current_node_id, but no approval_state.
        run = self._make_run(status="paused", current_node_id="n1")

        with self.assertRaises(HTTPException) as ctx:
            self.service.approve_batch(run_id=run.id, user_id=USER_ID)
        self.assertEqual(ctx.exception.status_code, 409)
        self.mock_hatchet.event.push.assert_not_called()

    def test_approve_batch_pushes_correct_event_key(self) -> None:
        run = self._make_run(
            status="paused",
            approval_state={"awaiting": True, "next_batch_index": 2, "total_batches": 5},
        )

        self.service.approve_batch(run_id=run.id, user_id=USER_ID)

        self.mock_hatchet.event.push.assert_called_once()
        args, kwargs = self.mock_hatchet.event.push.call_args
        expected_key = batch_approval_event_key(run.uuid, 2)
        self.assertEqual(args[0], expected_key)
        self.assertEqual(kwargs.get("scope"), expected_key)

    def test_approve_all_sets_auto_approve_flag_before_pushing_event(self) -> None:
        run = self._make_run(
            status="paused",
            approval_state={"awaiting": True, "next_batch_index": 0, "total_batches": 3},
        )

        observed: dict = {}

        def _capture_push(*args, **kwargs):
            self.db.refresh(run)
            observed["auto_approve_remaining"] = run.approval_state.get(
                "auto_approve_remaining"
            )

        self.mock_hatchet.event.push.side_effect = _capture_push

        self.service.approve_all(run_id=run.id, user_id=USER_ID)

        self.assertTrue(observed["auto_approve_remaining"])
        self.mock_hatchet.event.push.assert_called_once()

    def test_approve_all_pushes_next_batch_index(self) -> None:
        run = self._make_run(
            status="paused",
            approval_state={"awaiting": True, "next_batch_index": 1, "total_batches": 4},
        )

        self.service.approve_all(run_id=run.id, user_id=USER_ID)

        expected_key = batch_approval_event_key(run.uuid, 1)
        self.mock_hatchet.event.push.assert_called_once()
        args, _kwargs = self.mock_hatchet.event.push.call_args
        self.assertEqual(args[0], expected_key)

    def test_approve_batch_404_for_missing_run(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            self.service.approve_batch(run_id=999, user_id=USER_ID)
        self.assertEqual(ctx.exception.status_code, 404)

    # ─── step_run / continue_run guards against an approval pause ──────────

    def test_step_run_409_when_awaiting_batch_approval(self) -> None:
        run = self._make_run(
            status="paused",
            current_node_id="inv",
            approval_state={"awaiting": True, "next_batch_index": 0, "total_batches": 2},
        )

        with self.assertRaises(HTTPException) as ctx:
            self.service.step_run(run_id=run.id, user_id=USER_ID)
        self.assertEqual(ctx.exception.status_code, 409)
        self.mock_hatchet.event.push.assert_not_called()

    def test_continue_run_409_when_awaiting_batch_approval(self) -> None:
        run = self._make_run(
            status="paused",
            current_node_id="inv",
            approval_state={"awaiting": True, "next_batch_index": 0, "total_batches": 2},
        )

        with self.assertRaises(HTTPException) as ctx:
            self.service.continue_run(run_id=run.id, user_id=USER_ID)
        self.assertEqual(ctx.exception.status_code, 409)
        self.mock_hatchet.event.push.assert_not_called()

    def test_step_run_still_works_for_a_plain_debug_pause(self) -> None:
        run = self._make_run(status="paused", current_node_id="n1")

        self.service.step_run(run_id=run.id, user_id=USER_ID)

        expected_key = debug_step_event_key(run.uuid, "n1")
        self.mock_hatchet.event.push.assert_called_once()
        args, _kwargs = self.mock_hatchet.event.push.call_args
        self.assertEqual(args[0], expected_key)


if __name__ == "__main__":
    unittest.main()
