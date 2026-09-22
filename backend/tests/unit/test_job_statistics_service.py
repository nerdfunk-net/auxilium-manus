"""Tests for JobStatisticsService."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.domain_exceptions import AccessDeniedError, NotFoundError
from core.models.base import Base
from core.models.job_statistics import JobStatistic
from core.models.users import User
from core.models.workflows import Workflow
from repositories.job_statistics_repository import JobStatisticsRepository
from services.statistics.job_statistics_service import JobStatisticsService


class JobStatisticsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine, tables=[User.__table__, Workflow.__table__, JobStatistic.__table__]
        )
        self.addCleanup(engine.dispose)
        Session = sessionmaker(bind=engine)
        self.db = Session()
        self.addCleanup(self.db.close)
        self.service = JobStatisticsService(self.db)
        self.repo = JobStatisticsRepository(self.db)

    def _workflow(self, *, name: str, visibility: str, creator_id: int) -> Workflow:
        workflow = Workflow(name=name, visibility=visibility, creator_id=creator_id)
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def _record(self, workflow: Workflow, *, run_id: int, result: str, device_name: str) -> None:
        self.repo.create_batch(
            [
                {
                    "run_id": run_id,
                    "node_id": "collect-statistics-1",
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "device_name": device_name,
                    "result": result,
                }
            ]
        )

    def test_list_jobs_with_stats_returns_latest_run_counts(self) -> None:
        workflow = self._workflow(name="Get Backups", visibility="public", creator_id=1)
        self._record(workflow, run_id=1, result="success", device_name="r1")
        self._record(workflow, run_id=2, result="success", device_name="r1")
        self._record(workflow, run_id=2, result="failed", device_name="r2")

        response = self.service.list_jobs_with_stats(user_id=1)

        self.assertEqual(len(response.jobs), 1)
        item = response.jobs[0]
        self.assertEqual(item.workflow_id, workflow.id)
        self.assertEqual(item.latest_run_id, 2)
        self.assertEqual(item.success_count, 1)
        self.assertEqual(item.failed_count, 1)
        self.assertEqual(item.total_count, 2)

    def test_list_jobs_with_stats_hides_private_workflows_from_others(self) -> None:
        workflow = self._workflow(name="Private Job", visibility="private", creator_id=1)
        self._record(workflow, run_id=1, result="success", device_name="r1")

        response = self.service.list_jobs_with_stats(user_id=2)
        self.assertEqual(response.jobs, [])

    def test_get_pie_data_returns_latest_run(self) -> None:
        workflow = self._workflow(name="Get Backups", visibility="public", creator_id=1)
        self._record(workflow, run_id=1, result="success", device_name="r1")
        self._record(workflow, run_id=2, result="failed", device_name="r1")

        response = self.service.get_pie_data(user_id=1, workflow_id=workflow.id)
        self.assertEqual(response.run_id, 2)
        self.assertEqual(response.success_count, 0)
        self.assertEqual(response.failed_count, 1)
        self.assertEqual(response.total_count, 1)

    def test_get_pie_data_unknown_workflow_raises_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.get_pie_data(user_id=1, workflow_id=999)

    def test_get_pie_data_no_stats_yet_raises_not_found(self) -> None:
        workflow = self._workflow(name="Fresh Job", visibility="public", creator_id=1)
        with self.assertRaises(NotFoundError):
            self.service.get_pie_data(user_id=1, workflow_id=workflow.id)

    def test_get_pie_data_private_workflow_denies_other_user(self) -> None:
        workflow = self._workflow(name="Private Job", visibility="private", creator_id=1)
        self._record(workflow, run_id=1, result="success", device_name="r1")

        with self.assertRaises(AccessDeniedError):
            self.service.get_pie_data(user_id=2, workflow_id=workflow.id)


if __name__ == "__main__":
    unittest.main()
