"""Tests for RunService.delete_run.

Covers the terminal-status guard (only success/failed/cancelled runs may be
deleted), cascade deletion of step results, and the standard 404/403 access
checks shared with the other run-mutation endpoints.
"""

from __future__ import annotations

import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from services.execution.run_service import RunService

USER_ID = 1
OTHER_USER_ID = 2


class RunServiceDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

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

        for user_id, username in ((USER_ID, "tester"), (OTHER_USER_ID, "owner")):
            user = User(username=username, password_hash="hash", is_active=True)
            user.id = user_id
            self.db.add(user)
        self.db.commit()

        workflow = Workflow(name="wf-1", creator_id=USER_ID, visibility="public")
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        self.workflow = workflow

        private_workflow = Workflow(
            name="wf-private", creator_id=OTHER_USER_ID, visibility="private"
        )
        self.db.add(private_workflow)
        self.db.commit()
        self.db.refresh(private_workflow)
        self.private_workflow = private_workflow

        self.service = RunService(self.db)

    def _make_run(self, *, workflow_id: int | None = None, **overrides) -> WorkflowRun:
        defaults = dict(
            uuid="run-uuid-1",
            workflow_id=workflow_id or self.workflow.id,
            triggered_by_id=None,
            status="success",
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

    def test_delete_run_succeeds_for_each_terminal_status(self) -> None:
        for status_value in ("success", "failed", "cancelled"):
            with self.subTest(status=status_value):
                run = self._make_run(uuid=f"run-{status_value}", status=status_value)
                run_id = run.id

                self.service.delete_run(run_id=run_id, user_id=USER_ID)

                self.assertIsNone(self.service.run_repo.get_run_by_id(run_id))

    def test_delete_run_cascades_to_step_results(self) -> None:
        run = self._make_run(status="success")
        step = WorkflowStepResult(
            run_id=run.id,
            step_node_id="n1",
            step_type="log-message",
            step_name="Log",
            status="success",
        )
        self.db.add(step)
        self.db.commit()
        self.db.refresh(step)
        step_id = step.id

        self.service.delete_run(run_id=run.id, user_id=USER_ID)

        remaining = (
            self.db.query(WorkflowStepResult).filter(WorkflowStepResult.id == step_id).first()
        )
        self.assertIsNone(remaining)

    def test_delete_run_400_for_non_terminal_statuses(self) -> None:
        for status_value in ("pending", "running", "paused"):
            with self.subTest(status=status_value):
                run = self._make_run(uuid=f"run-{status_value}", status=status_value)

                with self.assertRaises(HTTPException) as ctx:
                    self.service.delete_run(run_id=run.id, user_id=USER_ID)
                self.assertEqual(ctx.exception.status_code, 400)
                self.assertIsNotNone(self.service.run_repo.get_run_by_id(run.id))

    def test_delete_run_404_for_missing_run(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            self.service.delete_run(run_id=999, user_id=USER_ID)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_delete_run_403_for_private_workflow_not_owned(self) -> None:
        run = self._make_run(workflow_id=self.private_workflow.id, status="success")

        with self.assertRaises(HTTPException) as ctx:
            self.service.delete_run(run_id=run.id, user_id=USER_ID)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIsNotNone(self.service.run_repo.get_run_by_id(run.id))


if __name__ == "__main__":
    unittest.main()
