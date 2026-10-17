"""O2-01 / O2-06: a Hatchet outage must not take the API down with it.

* No pooled database connection is held while the call to Hatchet is in flight (it used to be held
  for the ~17 s the SDK retries, so a burst of triggers emptied the pool and every other request
  waited for a connection).
* The failure is a 503 that says what is wrong, not a bare 500.
* After a failed dispatch the next ones fail at once instead of each blocking a worker thread.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.background_tier import WorkflowBackgroundTier
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from models.runs import WorkflowRunCreate
from models.workflow_validation import WorkflowValidationResult
from services.execution.dispatch_breaker import DispatchBreaker
from services.execution.run_service import RunService

USER_ID = 1


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class DispatchBreakerTests(unittest.TestCase):
    def test_starts_closed(self) -> None:
        self.assertFalse(DispatchBreaker(open_seconds=10, clock=_Clock()).is_open())

    def test_opens_after_a_failure_and_closes_after_the_window(self) -> None:
        clock = _Clock()
        breaker = DispatchBreaker(open_seconds=10, clock=clock)
        breaker.record_failure()
        self.assertTrue(breaker.is_open())
        clock.now += 9.9
        self.assertTrue(breaker.is_open())
        clock.now += 0.2
        self.assertFalse(breaker.is_open())

    def test_a_success_closes_it_at_once(self) -> None:
        breaker = DispatchBreaker(open_seconds=10, clock=_Clock())
        breaker.record_failure()
        breaker.record_success()
        self.assertFalse(breaker.is_open())

    def test_reset_closes_it(self) -> None:
        breaker = DispatchBreaker(open_seconds=10, clock=_Clock())
        breaker.record_failure()
        breaker.reset()
        self.assertFalse(breaker.is_open())


class RunDispatchResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # A file database gets a real QueuePool, so checked-out connections can be counted.
        self.engine = create_engine(f"sqlite:///{Path(tmp.name) / 'runs.db'}")
        WorkflowRun.metadata.create_all(
            self.engine,
            tables=[
                User.__table__,
                Workflow.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
                WorkflowBackgroundTier.__table__,
            ],
        )
        self.addCleanup(self.engine.dispose)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.db.close)
        self.service = RunService(self.db)

        self.clock = _Clock()
        self.breaker = DispatchBreaker(open_seconds=15, clock=self.clock)
        breaker_patch = patch("services.execution.run_service.dispatch_breaker", self.breaker)
        breaker_patch.start()
        self.addCleanup(breaker_patch.stop)

        validator_patch = patch("services.execution.run_service.WorkflowValidationService")
        validator = validator_patch.start()
        validator.return_value.validate.return_value = WorkflowValidationResult(
            findings=[], has_errors=False
        )
        self.addCleanup(validator_patch.stop)

        workflow = Workflow(
            name="wf-1",
            creator_id=USER_ID,
            visibility="public",
            canvas_nodes=[{"id": "n1", "data": {"kind": "run-command", "pluginConfig": {}}}],
            canvas_edges=[],
        )
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        self.db.commit()  # end the read transaction of refresh()
        self.workflow_id = workflow.id

    def _patch_dispatch(self, **kwargs):
        run_no_wait = patch("hatchet.workflows.workflow_run.workflow.run_no_wait", **kwargs)
        mock = run_no_wait.start()
        self.addCleanup(run_no_wait.stop)
        return mock

    def _trigger(self):
        return self.service.trigger_run(
            workflow_id=self.workflow_id, data=WorkflowRunCreate(), user_id=USER_ID
        )

    def test_no_pooled_connection_is_held_while_hatchet_is_called(self) -> None:
        checked_out: list[int] = []

        def slow_dispatch(*_args, **_kwargs):
            checked_out.append(self.engine.pool.checkedout())
            return MagicMock(workflow_run_id="hatchet-1")

        self._patch_dispatch(side_effect=slow_dispatch)

        self._trigger()

        self.assertEqual(checked_out, [0])

    def test_a_successful_dispatch_still_records_the_hatchet_run(self) -> None:
        self._patch_dispatch(return_value=MagicMock(workflow_run_id="hatchet-1"))

        response = self._trigger()

        run = self.db.get(WorkflowRun, response.id)
        self.assertEqual((run.status, run.hatchet_run_id), ("pending", "hatchet-1"))

    def test_an_unreachable_engine_is_a_503_that_says_so(self) -> None:
        self._patch_dispatch(side_effect=ConnectionError("hatchet down"))

        with self.assertRaises(HTTPException) as ctx:
            self._trigger()

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("engine", ctx.exception.detail["message"].lower())
        self.assertIn("error_id", ctx.exception.detail)
        self.assertNotIn("hatchet down", str(ctx.exception.detail))
        run = self.db.query(WorkflowRun).one()
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_message, "Workflow execution engine unavailable")

    def test_after_a_failure_the_next_triggers_do_not_call_hatchet(self) -> None:
        run_no_wait = self._patch_dispatch(side_effect=ConnectionError("down"))

        for _ in range(3):
            with self.assertRaises(HTTPException) as ctx:
                self._trigger()
            self.assertEqual(ctx.exception.status_code, 503)

        self.assertEqual(run_no_wait.call_count, 1)
        self.assertEqual(self.db.query(WorkflowRun).filter_by(status="failed").count(), 3)

    def test_hatchet_is_tried_again_once_the_window_has_passed(self) -> None:
        run_no_wait = self._patch_dispatch(side_effect=ConnectionError("down"))
        with self.assertRaises(HTTPException):
            self._trigger()

        self.clock.now += 16
        run_no_wait.side_effect = None
        run_no_wait.return_value = MagicMock(workflow_run_id="hatchet-2")
        response = self._trigger()

        self.assertEqual(run_no_wait.call_count, 2)
        self.assertEqual(self.db.get(WorkflowRun, response.id).status, "pending")
        self.assertFalse(self.breaker.is_open())
