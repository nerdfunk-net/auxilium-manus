"""RunService responses carry live fan-out device-group progress."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.runs import WorkflowRun, WorkflowRunDeviceGroup, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from repositories.run_repository import RunRepository
from services.execution.run_service import RunService

USER_ID = 1


class RunServiceDeviceGroupTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Workflow.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
                WorkflowRunDeviceGroup.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        workflow = Workflow(name="wf-1", creator_id=USER_ID, visibility="public")
        self.db.add(workflow)
        self.db.commit()
        run = WorkflowRun(
            uuid="run-uuid-1",
            workflow_id=workflow.id,
            triggered_by_id=None,
            status="running",
            trigger_type="manual",
            device_ids=[],
        )
        self.db.add(run)
        self.db.commit()
        self.run = run
        self.repo = RunRepository(self.db)
        self.service = RunService(self.db)
        hatchet_patch = patch("hatchet.client.hatchet", new=MagicMock())
        hatchet_patch.start()
        self.addCleanup(hatchet_patch.stop)

    def test_get_run_includes_device_groups_ordered_with_node_states(self) -> None:
        self.repo.create_device_groups(run_id=self.run.id, groups=[(1, ["r2"]), (0, ["r1"])])
        self.repo.mark_device_group_started(run_id=self.run.id, child_index=0)
        self.repo.set_device_group_node_state(
            run_id=self.run.id, child_index=0, node_id="a", state="running"
        )

        response = self.service.get_run(self.run.id, USER_ID)

        self.assertEqual([g.child_index for g in response.device_groups], [0, 1])
        first = response.device_groups[0]
        self.assertEqual(first.status, "running")
        self.assertEqual(first.device_names, ["r1"])
        self.assertEqual(first.node_states, {"a": "running"})
        self.assertEqual(response.device_groups[1].status, "pending")

    def test_get_run_without_fan_out_has_no_device_groups(self) -> None:
        response = self.service.get_run(self.run.id, USER_ID)

        self.assertEqual(response.device_groups, [])

    def test_cancel_run_response_includes_device_groups(self) -> None:
        self.repo.create_device_groups(run_id=self.run.id, groups=[(0, ["r1"])])

        response = self.service.cancel_run(self.run.id, USER_ID)

        self.assertEqual(len(response.device_groups), 1)


if __name__ == "__main__":
    unittest.main()
