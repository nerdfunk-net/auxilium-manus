"""Tests for JobStatisticsRepository."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.job_statistics import JobStatistic
from core.models.workflows import Workflow
from repositories.job_statistics_repository import JobStatisticsRepository


class JobStatisticsRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[Workflow.__table__, JobStatistic.__table__])
        self.addCleanup(engine.dispose)
        Session = sessionmaker(bind=engine)
        self.db = Session()
        self.addCleanup(self.db.close)
        self.repo = JobStatisticsRepository(self.db)

    def _workflow(self, *, name: str, visibility: str, creator_id: int) -> Workflow:
        workflow = Workflow(name=name, visibility=visibility, creator_id=creator_id)
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def test_create_batch_inserts_rows(self) -> None:
        rows = [
            {
                "run_id": 1,
                "node_id": "collect-statistics-1",
                "workflow_id": 42,
                "workflow_name": "Get Backups",
                "device_name": "router1",
                "result": "success",
            },
            {
                "run_id": 1,
                "node_id": "collect-statistics-2",
                "workflow_id": 42,
                "workflow_name": "Get Backups",
                "device_name": "router2",
                "result": "failed",
            },
        ]
        created = self.repo.create_batch(rows)
        self.assertEqual(len(created), 2)
        self.assertTrue(all(stat.id is not None for stat in created))

    def test_get_latest_run_id_picks_max(self) -> None:
        self.repo.create_batch(
            [
                {
                    "run_id": 5,
                    "node_id": "n1",
                    "workflow_id": 1,
                    "workflow_name": "Job A",
                    "device_name": "r1",
                    "result": "success",
                },
                {
                    "run_id": 9,
                    "node_id": "n1",
                    "workflow_id": 1,
                    "workflow_name": "Job A",
                    "device_name": "r1",
                    "result": "success",
                },
            ]
        )
        self.assertEqual(self.repo.get_latest_run_id(1), 9)
        self.assertIsNone(self.repo.get_latest_run_id(999))

    def test_get_run_counts_groups_by_result(self) -> None:
        self.repo.create_batch(
            [
                {
                    "run_id": 7,
                    "node_id": "n-success",
                    "workflow_id": 1,
                    "workflow_name": "Job A",
                    "device_name": "r1",
                    "result": "success",
                },
                {
                    "run_id": 7,
                    "node_id": "n-success",
                    "workflow_id": 1,
                    "workflow_name": "Job A",
                    "device_name": "r2",
                    "result": "success",
                },
                {
                    "run_id": 7,
                    "node_id": "n-failed",
                    "workflow_id": 1,
                    "workflow_name": "Job A",
                    "device_name": "r3",
                    "result": "failed",
                },
            ]
        )
        success_count, failed_count = self.repo.get_run_counts(7)
        self.assertEqual((success_count, failed_count), (2, 1))
        self.assertEqual(self.repo.get_run_counts(999), (0, 0))

    def test_get_run_created_at_returns_earliest_row(self) -> None:
        self.repo.create_batch(
            [
                {
                    "run_id": 3,
                    "node_id": "n1",
                    "workflow_id": 1,
                    "workflow_name": "Job A",
                    "device_name": "r1",
                    "result": "success",
                }
            ]
        )
        self.assertIsNotNone(self.repo.get_run_created_at(3))
        self.assertIsNone(self.repo.get_run_created_at(999))

    def test_list_workflow_ids_with_stats_visibility_filtering(self) -> None:
        public_wf = self._workflow(name="Public Job", visibility="public", creator_id=1)
        own_private_wf = self._workflow(name="My Private Job", visibility="private", creator_id=2)
        other_private_wf = self._workflow(
            name="Someone Else's Job", visibility="private", creator_id=3
        )

        for wf in (public_wf, own_private_wf, other_private_wf):
            self.repo.create_batch(
                [
                    {
                        "run_id": wf.id,
                        "node_id": "n1",
                        "workflow_id": wf.id,
                        "workflow_name": wf.name,
                        "device_name": "r1",
                        "result": "success",
                    }
                ]
            )

        visible = self.repo.list_workflow_ids_with_stats(user_id=2)
        visible_ids = {row[0] for row in visible}
        self.assertEqual(visible_ids, {public_wf.id, own_private_wf.id})

    def test_list_workflow_ids_with_stats_excludes_workflows_without_stats(self) -> None:
        self._workflow(name="No stats yet", visibility="public", creator_id=1)
        self.assertEqual(self.repo.list_workflow_ids_with_stats(user_id=1), [])


if __name__ == "__main__":
    unittest.main()
