"""Tests for RunService.get_attribute_path_tree / resolve_attribute_path.

Covers the standard 404/403 access checks shared with other run-read
endpoints, graceful behavior when no step result matches the requested
ancestor node ids, and that resolve returns one row per merged device.
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from core.domain_exceptions import DomainError
from core.models.change_requests import ChangeRequest
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from models.workflow_context import DeviceContext, WorkflowContext
from services.execution.run_service import RunService

USER_ID = 1
OTHER_USER_ID = 2


class RunServiceAttributePathTests(unittest.TestCase):
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
                ChangeRequest.__table__,
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
            device_ids=[],
        )
        defaults.update(overrides)
        run = WorkflowRun(**defaults)
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def _add_step_result(
        self, run: WorkflowRun, *, step_node_id: str, devices: dict[str, DeviceContext]
    ) -> WorkflowStepResult:
        step = WorkflowStepResult(
            run_id=run.id,
            step_node_id=step_node_id,
            step_type="noop",
            step_name="Noop",
            status="success",
            output={
                "outcomes": {
                    "success": WorkflowContext(
                        run_id=run.uuid, workflow_id=str(run.workflow_id), devices=devices
                    ).model_dump(mode="json")
                }
            },
        )
        self.db.add(step)
        self.db.commit()
        self.db.refresh(step)
        return step

    def test_404_for_missing_run(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.service.get_attribute_path_tree(
                run_id=999, user_id=USER_ID, ancestor_node_ids=["a"]
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_403_for_private_workflow_not_owned(self) -> None:
        run = self._make_run(workflow_id=self.private_workflow.id)
        with self.assertRaises(DomainError) as ctx:
            self.service.get_attribute_path_tree(
                run_id=run.id, user_id=USER_ID, ancestor_node_ids=["a"]
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_empty_tree_when_no_step_result_matches_ancestors(self) -> None:
        run = self._make_run()
        self._add_step_result(
            run,
            step_node_id="downstream-only",
            devices={"d1": DeviceContext(id="d1", name="d1", hostname="d1")},
        )

        response = self.service.get_attribute_path_tree(
            run_id=run.id, user_id=USER_ID, ancestor_node_ids=["not-an-ancestor"]
        )

        self.assertEqual(response.device_count, 0)
        self.assertEqual(response.ancestor_node_ids, [])
        # "device" namespace is always present even with zero devices.
        self.assertTrue(any(n.name == "device" for n in response.nodes))

    def test_tree_reflects_ancestor_step_output(self) -> None:
        run = self._make_run()
        self._add_step_result(
            run,
            step_node_id="batfish-facts",
            devices={
                "d1": DeviceContext(
                    id="d1",
                    name="d1",
                    hostname="d1",
                    parsed={"batfish_extract_facts": {"parsed": {"TACACS": {"key": "shared"}}}},
                )
            },
        )

        response = self.service.get_attribute_path_tree(
            run_id=run.id, user_id=USER_ID, ancestor_node_ids=["batfish-facts"]
        )

        self.assertEqual(response.device_count, 1)
        self.assertEqual(response.ancestor_node_ids, ["batfish-facts"])
        parsed_node = next(n for n in response.nodes if n.name == "parsed")
        self.assertTrue(any(c.name == "batfish_extract_facts" for c in parsed_node.children))

    def test_resolve_returns_one_row_per_merged_device(self) -> None:
        run = self._make_run()
        self._add_step_result(
            run,
            step_node_id="a",
            devices={
                "d1": DeviceContext(id="d1", name="d1", hostname="d1", network_driver="cisco_ios"),
                "d2": DeviceContext(id="d2", name="d2", hostname="d2", network_driver="arista_eos"),
            },
        )

        response = self.service.resolve_attribute_path(
            run_id=run.id, user_id=USER_ID, path="device.network_driver", ancestor_node_ids=["a"]
        )

        self.assertEqual(len(response.results), 2)
        by_device = {r.device_id: r for r in response.results}
        self.assertEqual(by_device["d1"].state, "present")
        self.assertEqual(by_device["d1"].value, "cisco_ios")
        self.assertEqual(by_device["d2"].value, "arista_eos")

    def test_resolve_404_for_missing_run(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.service.resolve_attribute_path(
                run_id=999, user_id=USER_ID, path="device.name", ancestor_node_ids=[]
            )
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
