"""Tests for Wait & Run batch-approval gating in ``_dispatch_children``.

These exercise the batch-sequential dispatch loop (hatchet/workflows/workflow_run.py)
against a real in-memory SQLite-backed WorkflowRun session (shared across the
short-lived ``SessionLocal()`` sessions the dispatch loop opens per gate, via a
StaticPool connection), with the Hatchet ``child_workflow.aio_run`` call and the
durable ``ctx.aio_wait_for_event`` wait stubbed out. See doc/WAIT-AND-RUN.md §6.3.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from hatchet.workflows import workflow_run as wf_run_module
from hatchet.workflows.workflow_run import _dispatch_children
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from repositories.run_repository import RunRepository
from services.execution.run_events import batch_approval_event_key
from services.execution.step_runner import FanOutSignal


def _make_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _device(did: str) -> DeviceContext:
    return DeviceContext(
        id=did,
        name=did,
        hostname=did,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _make_signal(
    device_count: int,
    *,
    mode: str = "per_device",
    chunk_size: int = 1,
    approval: dict[str, Any] | None = None,
) -> FanOutSignal:
    devices = {f"d{i}": _device(f"d{i}") for i in range(device_count)}
    context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices)
    fan_out_config: dict[str, Any] = {
        "enabled": True,
        "mode": mode,
        "chunk_size": chunk_size,
        "max_concurrency": 0,
        "approval": approval
        or {"enabled": False, "batch_size": 1, "first_batch_auto": True},
    }
    return FanOutSignal(
        inventory_node_id="inv",
        fan_out_config=fan_out_config,
        inventory_outcome=context,
        join_node_id=None,
    )


class WaitAndRunDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        WorkflowRun.metadata.create_all(
            self.engine,
            tables=[User.__table__, WorkflowRun.__table__, WorkflowStepResult.__table__],
        )
        self.addCleanup(self.engine.dispose)
        self.test_sessionmaker = sessionmaker(bind=self.engine)

        self.db: Session = self.test_sessionmaker()
        self.addCleanup(self.db.close)
        self.run_repo = RunRepository(self.db)

        self.run = WorkflowRun(
            uuid="run-uuid-1",
            workflow_id=1,
            triggered_by_id=None,
            status="running",
            trigger_type="manual",
            run_mode="normal",
            device_ids=[],
        )
        self.db.add(self.run)
        self.db.commit()
        self.db.refresh(self.run)

        session_patch = patch("core.database.SessionLocal", new=self.test_sessionmaker)
        session_patch.start()
        self.addCleanup(session_patch.stop)

        child_run = AsyncMock(return_value={"execute_device_group": {}})
        child_patch = patch.object(wf_run_module.child_workflow, "aio_run", child_run)
        child_patch.start()
        self.addCleanup(child_patch.stop)
        self.child_run = child_run

    def _reload_run(self) -> WorkflowRun:
        # self.db is a long-lived session distinct from the short-lived
        # SessionLocal() sessions _dispatch_children opens per gate; its
        # identity-mapped `run` instance isn't expired, so a plain re-select
        # would return stale attributes instead of the other session's commit.
        result = self.run_repo.get_run_by_id(self.run.id)
        assert result is not None
        run, _ = result
        self.db.refresh(run)
        return run

    async def _dispatch(self, signal: FanOutSignal, ctx: AsyncMock) -> list[Any]:
        return await _dispatch_children(
            signal,
            self.run.id,
            ctx=ctx,
            run_uuid=self.run.uuid,
            canvas_nodes=[{"id": "inv"}],
            canvas_edges=[],
        )

    async def test_approval_disabled_dispatches_all_at_once_no_waits(self) -> None:
        signal = _make_signal(6, mode="per_device")
        ctx = AsyncMock()

        results = await self._dispatch(signal, ctx)

        self.assertEqual(len(results), 6)
        ctx.aio_wait_for_event.assert_not_called()
        self.assertEqual(self.child_run.await_count, 6)

    async def test_first_batch_auto_true_waits_only_for_later_batches(self) -> None:
        # 6 devices, batch_size=2 -> 3 batches. first_batch_auto=True skips the
        # gate before batch 0 but not before batches 1 and 2.
        signal = _make_signal(
            6,
            mode="per_device",
            approval={"enabled": True, "batch_size": 2, "first_batch_auto": True},
        )
        ctx = AsyncMock()

        results = await self._dispatch(signal, ctx)

        self.assertEqual(len(results), 6)
        expected_keys = [
            batch_approval_event_key("run-uuid-1", idx) for idx in (1, 2)
        ]
        actual_keys = [call.args[0] for call in ctx.aio_wait_for_event.await_args_list]
        self.assertEqual(actual_keys, expected_keys)

    async def test_first_batch_auto_false_waits_before_first_batch_too(self) -> None:
        signal = _make_signal(
            4,
            mode="per_device",
            approval={"enabled": True, "batch_size": 2, "first_batch_auto": False},
        )
        ctx = AsyncMock()

        results = await self._dispatch(signal, ctx)

        self.assertEqual(len(results), 4)
        expected_keys = [
            batch_approval_event_key("run-uuid-1", idx) for idx in (0, 1)
        ]
        actual_keys = [call.args[0] for call in ctx.aio_wait_for_event.await_args_list]
        self.assertEqual(actual_keys, expected_keys)

    async def test_auto_approve_remaining_skips_further_waits(self) -> None:
        # 3 batches (batch_size=2, 6 devices), first_batch_auto=True: gates
        # before batch 1 and batch 2. Simulate an "approve-all" click landing
        # while the run is paused before batch 1 -- batch 2's gate must not fire.
        signal = _make_signal(
            6,
            mode="per_device",
            approval={"enabled": True, "batch_size": 2, "first_batch_auto": True},
        )
        ctx = AsyncMock()

        async def _wait_side_effect(_event_key: str, **_kwargs: Any) -> dict[str, Any]:
            run = self._reload_run()
            self.run_repo.update_run_status(
                run,
                status="paused",
                approval_state={**(run.approval_state or {}), "auto_approve_remaining": True},
            )
            return {}

        ctx.aio_wait_for_event.side_effect = _wait_side_effect

        results = await self._dispatch(signal, ctx)

        self.assertEqual(len(results), 6)
        # Only one wait: before batch 1. Batch 2's gate is skipped because
        # auto_approve_remaining was set during that wait.
        self.assertEqual(ctx.aio_wait_for_event.await_count, 1)
        self.assertEqual(
            ctx.aio_wait_for_event.await_args_list[0].args[0],
            batch_approval_event_key("run-uuid-1", 1),
        )

    async def test_run_paused_awaiting_before_wait_running_after(self) -> None:
        signal = _make_signal(
            4,
            mode="per_device",
            approval={"enabled": True, "batch_size": 2, "first_batch_auto": False},
        )
        ctx = AsyncMock()
        # Both batch 0 and batch 1 gate here (first_batch_auto=False) -- only
        # the first invocation's snapshot is under test.
        observations: list[dict[str, Any]] = []

        async def _wait_side_effect(_event_key: str, **_kwargs: Any) -> dict[str, Any]:
            run = self._reload_run()
            observations.append(
                {
                    "status": run.status,
                    "awaiting": (run.approval_state or {}).get("awaiting"),
                    "next_batch_index": (run.approval_state or {}).get("next_batch_index"),
                    "total_batches": (run.approval_state or {}).get("total_batches"),
                    "device_names": (run.approval_state or {}).get(
                        "next_batch_device_names"
                    ),
                }
            )
            return {}

        ctx.aio_wait_for_event.side_effect = _wait_side_effect

        await self._dispatch(signal, ctx)

        observed = observations[0]
        self.assertEqual(observed["status"], "paused")
        self.assertTrue(observed["awaiting"])
        self.assertEqual(observed["next_batch_index"], 0)
        self.assertEqual(observed["total_batches"], 2)
        self.assertEqual(observed["device_names"], ["d0", "d1"])

        final_run = self._reload_run()
        self.assertEqual(final_run.status, "running")
        self.assertFalse((final_run.approval_state or {}).get("awaiting"))

    async def test_chunked_mode_batches_chunks_not_devices(self) -> None:
        # 6 devices, chunk_size=3 -> 2 chunks (groups). batch_size=1 group per
        # batch -> 2 batches, gated between them.
        signal = _make_signal(
            6,
            mode="chunked",
            chunk_size=3,
            approval={"enabled": True, "batch_size": 1, "first_batch_auto": True},
        )
        ctx = AsyncMock()

        results = await self._dispatch(signal, ctx)

        # One child workflow per chunk (2 groups total).
        self.assertEqual(len(results), 2)
        self.assertEqual(ctx.aio_wait_for_event.await_count, 1)
        self.assertEqual(
            ctx.aio_wait_for_event.await_args_list[0].args[0],
            batch_approval_event_key("run-uuid-1", 1),
        )


if __name__ == "__main__":
    unittest.main()
