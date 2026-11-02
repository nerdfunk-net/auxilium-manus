"""Tests for DashboardService: cron/once next-run computation and the
public-or-mine workflow visibility predicate applied to schedules/runs,
against a real in-memory SQLite-backed session."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.runs import WorkflowRun
from core.models.schedules import WorkflowSchedule
from core.models.users import User
from core.models.workflows import Workflow
from services.dashboard.dashboard_service import DashboardService, _compute_next_run


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    User.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Workflow.__table__,
            WorkflowSchedule.__table__,
            WorkflowRun.__table__,
        ],
    )
    return sessionmaker(bind=engine)()


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, password_hash="hash", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_workflow(
    db: Session, *, name: str, creator_id: int, visibility: str = "private"
) -> Workflow:
    workflow = Workflow(name=name, creator_id=creator_id, visibility=visibility)
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


class ComputeNextRunTests(unittest.TestCase):
    def test_once_schedule_returns_run_at(self) -> None:
        run_at = datetime(2030, 1, 1, tzinfo=UTC)
        schedule = WorkflowSchedule(
            workflow_id=1, uuid="u", schedule_type="once", run_at=run_at, enabled=True
        )
        self.assertEqual(_compute_next_run(schedule), run_at)

    def test_cron_schedule_computes_next_occurrence_after_now(self) -> None:
        before_call = datetime.now(UTC)
        schedule = WorkflowSchedule(
            workflow_id=1,
            uuid="u",
            schedule_type="cron",
            cron_expression="* * * * *",
            enabled=True,
        )
        next_run = _compute_next_run(schedule)
        assert next_run is not None
        # Compare against a timestamp captured before the call (not a fresh
        # `now()` after it) so this can't race a minute boundary: the value
        # `_compute_next_run` computed internally is always >= before_call.
        self.assertGreater(next_run, before_call)

    def test_cron_schedule_advances_past_stale_last_triggered_at(self) -> None:
        before_call = datetime.now(UTC)
        schedule = WorkflowSchedule(
            workflow_id=1,
            uuid="u",
            schedule_type="cron",
            cron_expression="* * * * *",
            enabled=True,
            last_triggered_at=before_call - timedelta(days=30),
        )
        next_run = _compute_next_run(schedule)
        assert next_run is not None
        self.assertGreater(next_run, before_call)

    def test_malformed_cron_expression_returns_none(self) -> None:
        schedule = WorkflowSchedule(
            workflow_id=1,
            uuid="u",
            schedule_type="cron",
            cron_expression="not a cron",
            enabled=True,
        )
        self.assertIsNone(_compute_next_run(schedule))

    def test_cron_schedule_without_expression_returns_none(self) -> None:
        schedule = WorkflowSchedule(
            workflow_id=1, uuid="u", schedule_type="cron", cron_expression=None, enabled=True
        )
        self.assertIsNone(_compute_next_run(schedule))


class DashboardServiceVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        self.service = DashboardService(self.db)
        self.owner = _make_user(self.db, "owner")
        self.other = _make_user(self.db, "other")

    def test_list_schedules_includes_public_and_own_private(self) -> None:
        public_wf = _make_workflow(
            self.db, name="public-wf", creator_id=self.owner.id, visibility="public"
        )
        own_private_wf = _make_workflow(
            self.db, name="own-private-wf", creator_id=self.other.id, visibility="private"
        )
        others_private_wf = _make_workflow(
            self.db, name="others-private-wf", creator_id=self.owner.id, visibility="private"
        )
        for workflow in (public_wf, own_private_wf, others_private_wf):
            self.db.add(
                WorkflowSchedule(
                    workflow_id=workflow.id,
                    uuid=f"u-{workflow.id}",
                    schedule_type="once",
                    run_at=datetime.now(UTC),
                    enabled=True,
                )
            )
        self.db.commit()

        result = self.service.list_schedules(self.other.id)

        workflow_ids = {item.workflow_id for item in result.schedules}
        self.assertIn(public_wf.id, workflow_ids)
        self.assertIn(own_private_wf.id, workflow_ids)
        self.assertNotIn(others_private_wf.id, workflow_ids)

    def test_list_schedules_excludes_disabled(self) -> None:
        workflow = _make_workflow(
            self.db, name="wf", creator_id=self.other.id, visibility="private"
        )
        self.db.add(
            WorkflowSchedule(
                workflow_id=workflow.id,
                uuid="u",
                schedule_type="once",
                run_at=datetime.now(UTC),
                enabled=False,
            )
        )
        self.db.commit()

        result = self.service.list_schedules(self.other.id)

        self.assertEqual(result.schedules, [])

    def test_list_recent_runs_excludes_others_private_workflow(self) -> None:
        public_wf = _make_workflow(
            self.db, name="public-wf", creator_id=self.owner.id, visibility="public"
        )
        others_private_wf = _make_workflow(
            self.db, name="others-private-wf", creator_id=self.owner.id, visibility="private"
        )
        for workflow in (public_wf, others_private_wf):
            self.db.add(
                WorkflowRun(
                    uuid=f"run-{workflow.id}",
                    workflow_id=workflow.id,
                    triggered_by_id=self.owner.id,
                    status="success",
                    trigger_type="manual",
                )
            )
        self.db.commit()

        result = self.service.list_recent_runs(self.other.id, limit=10)

        workflow_ids = {item.workflow_id for item in result.runs}
        self.assertIn(public_wf.id, workflow_ids)
        self.assertNotIn(others_private_wf.id, workflow_ids)

    def test_repository_recent_runs_filters_by_workflow_and_status(self) -> None:
        from repositories.run_repository import RunRepository

        wf_a = _make_workflow(self.db, name="a", creator_id=self.owner.id, visibility="public")
        wf_b = _make_workflow(self.db, name="b", creator_id=self.owner.id, visibility="public")
        for uuid, wf, status in (
            ("r1", wf_a, "failed"),
            ("r2", wf_a, "success"),
            ("r3", wf_b, "failed"),
        ):
            self.db.add(
                WorkflowRun(
                    uuid=uuid,
                    workflow_id=wf.id,
                    triggered_by_id=self.owner.id,
                    status=status,
                    trigger_type="manual",
                )
            )
        self.db.commit()
        repo = RunRepository(self.db)

        failed = repo.list_recent_runs(self.owner.id, limit=10, statuses=["failed"])
        in_a = repo.list_recent_runs(self.owner.id, limit=10, workflow_id=wf_a.id)
        one = repo.list_recent_runs(self.owner.id, limit=1)

        self.assertEqual({r.uuid for r, _u, _n in failed}, {"r1", "r3"})
        self.assertEqual({r.uuid for r, _u, _n in in_a}, {"r1", "r2"})
        self.assertEqual(len(one), 1)

    def test_recent_runs_filters_keep_the_private_workflow_exclusion(self) -> None:
        from repositories.run_repository import RunRepository

        private_wf = _make_workflow(self.db, name="p", creator_id=self.owner.id)
        self.db.add(
            WorkflowRun(
                uuid="priv",
                workflow_id=private_wf.id,
                triggered_by_id=self.owner.id,
                status="failed",
                trigger_type="manual",
            )
        )
        self.db.commit()

        rows = RunRepository(self.db).list_recent_runs(
            self.other.id, limit=10, workflow_id=private_wf.id, statuses=["failed"]
        )

        self.assertEqual(rows, [])

    def test_service_rejects_skipped_and_caps_the_limit(self) -> None:
        from core.domain_exceptions import ValidationFailedError
        from services.execution.run_service import MAX_RECENT_RUNS, RunService

        service = RunService(self.db)
        with self.assertRaises(ValidationFailedError):
            service.list_recent_runs(self.owner.id, statuses=["skipped"])
        seen: dict[str, int] = {}
        original = service.run_repo.list_recent_runs

        def spy(user_id, *, limit, **kw):
            seen["limit"] = limit
            return original(user_id, limit=limit, **kw)

        service.run_repo.list_recent_runs = spy  # type: ignore[method-assign]
        service.list_recent_runs(self.owner.id, limit=10_000)
        self.assertEqual(seen["limit"], MAX_RECENT_RUNS)


if __name__ == "__main__":
    unittest.main()
