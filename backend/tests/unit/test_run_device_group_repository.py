"""RunRepository device-group progress methods (fan-out child progress)."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.runs import WorkflowRun, WorkflowRunDeviceGroup, WorkflowStepResult
from core.models.users import User
from repositories.run_repository import RunRepository


class RunDeviceGroupRepositoryTests(unittest.TestCase):
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
        self.repo = RunRepository(self.db)
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
        self.run_id = run.id

    def test_create_device_groups_makes_pending_rows_ordered_by_index(self) -> None:
        self.repo.create_device_groups(
            run_id=self.run_id, groups=[(1, ["r2"]), (0, ["r1"]), (2, ["r3", "r4"])]
        )

        groups = self.repo.list_device_groups(self.run_id)

        self.assertEqual([g.child_index for g in groups], [0, 1, 2])
        self.assertTrue(all(g.status == "pending" for g in groups))
        self.assertEqual(groups[2].device_names, ["r3", "r4"])
        self.assertEqual(groups[0].node_states, {})

    def test_create_device_groups_is_idempotent(self) -> None:
        self.repo.create_device_groups(run_id=self.run_id, groups=[(0, ["r1"])])
        self.repo.mark_device_group_started(run_id=self.run_id, child_index=0)

        self.repo.create_device_groups(run_id=self.run_id, groups=[(0, ["r1"]), (1, ["r2"])])

        groups = self.repo.list_device_groups(self.run_id)
        self.assertEqual([g.status for g in groups], ["running", "pending"])

    def test_mark_started_sets_running_and_started_at(self) -> None:
        self.repo.create_device_groups(run_id=self.run_id, groups=[(0, ["r1"])])

        self.repo.mark_device_group_started(run_id=self.run_id, child_index=0)

        group = self.repo.list_device_groups(self.run_id)[0]
        self.assertEqual(group.status, "running")
        self.assertIsNotNone(group.started_at)

    def test_set_node_state_accumulates_without_dropping_earlier_nodes(self) -> None:
        self.repo.create_device_groups(run_id=self.run_id, groups=[(0, ["r1"])])

        self.repo.set_device_group_node_state(
            run_id=self.run_id, child_index=0, node_id="a", state="running"
        )
        self.repo.set_device_group_node_state(
            run_id=self.run_id, child_index=0, node_id="a", state="success"
        )
        self.repo.set_device_group_node_state(
            run_id=self.run_id, child_index=0, node_id="b", state="running"
        )

        group = self.repo.list_device_groups(self.run_id)[0]
        self.assertEqual(group.node_states, {"a": "success", "b": "running"})

    def test_finish_device_group_records_status_error_and_finished_at(self) -> None:
        self.repo.create_device_groups(run_id=self.run_id, groups=[(0, ["r1"])])

        self.repo.finish_device_group(
            run_id=self.run_id, child_index=0, status="failed", error_message="boom"
        )

        group = self.repo.list_device_groups(self.run_id)[0]
        self.assertEqual(group.status, "failed")
        self.assertEqual(group.error_message, "boom")
        self.assertIsNotNone(group.finished_at)

    def test_updates_for_unknown_group_are_noops(self) -> None:
        self.repo.mark_device_group_started(run_id=self.run_id, child_index=9)
        self.repo.set_device_group_node_state(
            run_id=self.run_id, child_index=9, node_id="a", state="running"
        )
        self.repo.finish_device_group(run_id=self.run_id, child_index=9, status="success")

        self.assertEqual(self.repo.list_device_groups(self.run_id), [])

    def test_groups_are_scoped_per_run(self) -> None:
        other = WorkflowRun(
            uuid="run-uuid-2",
            workflow_id=1,
            triggered_by_id=None,
            status="running",
            trigger_type="manual",
            device_ids=[],
        )
        self.db.add(other)
        self.db.commit()
        self.repo.create_device_groups(run_id=self.run_id, groups=[(0, ["r1"])])
        self.repo.create_device_groups(run_id=other.id, groups=[(0, ["x1"]), (1, ["x2"])])

        self.assertEqual(len(self.repo.list_device_groups(self.run_id)), 1)
        self.assertEqual(len(self.repo.list_device_groups(other.id)), 2)


if __name__ == "__main__":
    unittest.main()
