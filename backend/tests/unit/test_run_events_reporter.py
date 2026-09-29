"""Run-event reporter: contextvar binding + thread-safe best-effort emission."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.runs import WorkflowRun, WorkflowRunEvent
from core.models.users import User
from repositories.run_event_repository import RunEventRepository
from services.execution.run_events_reporter import (
    RunEventContext,
    bound_run_event_context,
    build_connect_event_callback,
    current_run_event_context,
    emit_run_event,
)


class RunEventsReporterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        WorkflowRun.metadata.create_all(
            self.engine,
            tables=[User.__table__, WorkflowRun.__table__, WorkflowRunEvent.__table__],
        )
        self.addCleanup(self.engine.dispose)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db:
            run = WorkflowRun(
                uuid="run-1",
                workflow_id=1,
                triggered_by_id=None,
                status="running",
                trigger_type="manual",
                device_ids=[],
            )
            db.add(run)
            db.commit()
            self.run_id = run.id
        patcher = patch("core.database.SessionLocal", new=self.session_factory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _events(self) -> list[WorkflowRunEvent]:
        with self.session_factory() as db:
            return RunEventRepository(db).list_events(self.run_id)

    def test_no_context_by_default(self) -> None:
        self.assertIsNone(current_run_event_context())

    def test_bound_context_is_visible_and_restored(self) -> None:
        ctx = RunEventContext(run_id=self.run_id, node_id="a", child_index=1)

        with bound_run_event_context(ctx):
            self.assertEqual(current_run_event_context(), ctx)

        self.assertIsNone(current_run_event_context())

    def test_context_restored_even_when_body_raises(self) -> None:
        ctx = RunEventContext(run_id=self.run_id, node_id="a")

        with self.assertRaises(ValueError):
            with bound_run_event_context(ctx):
                raise ValueError("boom")

        self.assertIsNone(current_run_event_context())

    async def test_concurrent_tasks_keep_their_own_context(self) -> None:
        seen: dict[str, str | None] = {}

        async def node(node_id: str) -> None:
            with bound_run_event_context(RunEventContext(run_id=self.run_id, node_id=node_id)):
                await asyncio.sleep(0)
                ctx = current_run_event_context()
                seen[node_id] = ctx.node_id if ctx else None

        await asyncio.gather(node("a"), node("b"), node("c"))

        self.assertEqual(seen, {"a": "a", "b": "b", "c": "c"})

    def test_emit_persists_event_with_context_fields(self) -> None:
        ctx = RunEventContext(run_id=self.run_id, node_id="a", child_index=4)

        emit_run_event(
            ctx, kind="connect_retry", message="retrying", level="warning", device_name="r1"
        )

        (event,) = self._events()
        self.assertEqual(
            (event.step_node_id, event.child_index, event.device_name, event.level, event.kind),
            ("a", 4, "r1", "warning", "connect_retry"),
        )
        self.assertEqual(event.message, "retrying")

    def test_emit_never_raises_when_the_database_fails(self) -> None:
        ctx = RunEventContext(run_id=self.run_id, node_id="a")
        with patch("core.database.SessionLocal", side_effect=RuntimeError("db gone")):
            emit_run_event(ctx, kind="k", message="m")  # must not raise

    async def test_connect_callback_emits_from_a_worker_thread(self) -> None:
        ctx = RunEventContext(run_id=self.run_id, node_id="a", child_index=0)
        callback = build_connect_event_callback(ctx, device_name="10.0.0.1")

        await asyncio.get_running_loop().run_in_executor(
            None, callback, "connect_failed", "error", "timeout"
        )

        (event,) = self._events()
        self.assertEqual(
            (event.kind, event.level, event.device_name), ("connect_failed", "error", "10.0.0.1")
        )

    def test_connect_callback_is_none_without_context(self) -> None:
        self.assertIsNone(build_connect_event_callback(None, device_name="r1"))


if __name__ == "__main__":
    unittest.main()
