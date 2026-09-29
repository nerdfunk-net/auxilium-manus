"""Lifecycle of a fan-out child's ``WorkflowRunDeviceGroup`` row, and its
pre-creation by the parent's ``_dispatch_children``."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.runs import WorkflowRun, WorkflowRunDeviceGroup, WorkflowStepResult
from core.models.users import User
from hatchet.workflows import workflow_run as wf_run_module
from hatchet.workflows.device_group_execution import DeviceGroupInput, run_device_group
from hatchet.workflows.workflow_run import _dispatch_children
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from repositories.run_repository import RunRepository
from services.execution.step_runner import FanOutSignal, StepRunner


def _device(did: str) -> DeviceContext:
    return DeviceContext(
        id=did,
        name=did,
        hostname=did,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        WorkflowRun.metadata.create_all(
            self.engine,
            tables=[
                User.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
                WorkflowRunDeviceGroup.__table__,
            ],
        )
        self.addCleanup(self.engine.dispose)
        self.session_factory = sessionmaker(bind=self.engine)
        self.db = self.session_factory()
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
        patcher = patch("core.database.SessionLocal", new=self.session_factory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _groups(self) -> list[WorkflowRunDeviceGroup]:
        self.db.expire_all()
        return self.repo.list_device_groups(self.run_id)


class ExecuteDeviceGroupProgressTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.repo.create_device_groups(run_id=self.run_id, groups=[(2, ["d1"])])
        wf = SimpleNamespace(id=1, canvas_nodes=[{"id": "inv"}, {"id": "a"}], canvas_edges=[])
        wf_patch = patch(
            "repositories.workflow_repository.WorkflowRepository.get_by_id",
            return_value=(wf, None),
        )
        wf_patch.start()
        self.addCleanup(wf_patch.stop)
        child_ids = patch("services.execution.graph.child_node_ids", return_value={"a"})
        child_ids.start()
        self.addCleanup(child_ids.stop)
        ctx = WorkflowContext(run_id="r", workflow_id="1", devices={"d1": _device("d1")})
        self.input = DeviceGroupInput(
            parent_run_id=self.run_id,
            context_json=ctx.model_dump_json(),
            start_node_id="inv",
            child_index=2,
        )

    async def test_group_goes_running_then_success(self) -> None:
        seen_running: list[str] = []

        async def fake_subgraph(self_: Any, **kwargs: Any) -> Any:
            seen_running.append(next(g.status for g in self._groups()))
            progress = kwargs["progress"]
            await progress.node_started("a")
            await progress.node_finished("a", "success")
            return {}, {}

        with patch.object(StepRunner, "execute_subgraph", fake_subgraph):
            await run_device_group(self.input)

        self.assertEqual(seen_running, ["running"])
        group = self._groups()[0]
        self.assertEqual(group.status, "success")
        self.assertEqual(group.node_states, {"a": "success"})
        self.assertIsNotNone(group.finished_at)

    async def test_failed_node_makes_group_failed(self) -> None:
        async def fake_subgraph(self_: Any, **kwargs: Any) -> Any:
            await kwargs["progress"].node_finished("a", "failed")
            return {}, {"a": {"message": "unreachable", "category": "execution", "error_id": "e"}}

        with patch.object(StepRunner, "execute_subgraph", fake_subgraph):
            await run_device_group(self.input)

        self.assertEqual(self._groups()[0].status, "failed")

    async def test_crash_marks_group_failed_and_reraises(self) -> None:
        async def fake_subgraph(self_: Any, **kwargs: Any) -> Any:
            raise RuntimeError("worker exploded")

        with patch.object(StepRunner, "execute_subgraph", fake_subgraph):
            with self.assertRaises(RuntimeError):
                await run_device_group(self.input)

        group = self._groups()[0]
        self.assertEqual(group.status, "failed")
        self.assertIn("worker exploded", group.error_message or "")

    async def test_missing_group_row_does_not_break_the_child(self) -> None:
        self.db.query(WorkflowRunDeviceGroup).delete()
        self.db.commit()

        async def fake_subgraph(self_: Any, **kwargs: Any) -> Any:
            return {}, {}

        with patch.object(StepRunner, "execute_subgraph", fake_subgraph):
            result = await run_device_group(self.input)

        self.assertIn("__step_errors__", result)


class DispatchPrecreatesGroupsTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        child_run = AsyncMock(return_value={"execute_device_group": {}})
        patcher = patch.object(wf_run_module.child_workflow, "aio_run", child_run)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _signal(self, count: int, *, mode: str = "per_device", chunk_size: int = 1) -> FanOutSignal:
        devices = {f"d{i}": _device(f"d{i}") for i in range(count)}
        context = WorkflowContext(run_id="r", workflow_id="1", devices=devices)
        return FanOutSignal(
            inventory_node_id="inv",
            fan_out_config={
                "enabled": True,
                "mode": mode,
                "chunk_size": chunk_size,
                "max_concurrency": 0,
                "approval": {"enabled": False},
            },
            inventory_outcome=context,
            join_node_id=None,
        )

    async def _dispatch(self, signal: FanOutSignal) -> None:
        await _dispatch_children(
            signal,
            self.run_id,
            ctx=AsyncMock(),
            run_uuid="run-uuid-1",
            canvas_nodes=[{"id": "inv"}],
            canvas_edges=[],
        )

    async def test_per_device_mode_creates_one_pending_group_per_device(self) -> None:
        await self._dispatch(self._signal(3))

        groups = self._groups()
        self.assertEqual([g.child_index for g in groups], [0, 1, 2])
        self.assertEqual([g.device_names for g in groups], [["d0"], ["d1"], ["d2"]])
        self.assertTrue(all(g.status == "pending" for g in groups))

    async def test_chunked_mode_groups_devices_by_chunk(self) -> None:
        await self._dispatch(self._signal(5, mode="chunked", chunk_size=2))

        self.assertEqual(
            [g.device_names for g in self._groups()], [["d0", "d1"], ["d2", "d3"], ["d4"]]
        )

    async def test_group_creation_failure_does_not_block_dispatch(self) -> None:
        with patch.object(
            RunRepository, "create_device_groups", side_effect=RuntimeError("db gone")
        ):
            await self._dispatch(self._signal(2))

        self.assertEqual(wf_run_module.child_workflow.aio_run.await_count, 2)


if __name__ == "__main__":
    unittest.main()
