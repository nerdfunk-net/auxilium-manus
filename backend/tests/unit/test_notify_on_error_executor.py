"""Tests for notify-on-error executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from models.workflow_context import DeviceContext, DeviceError, DeviceStatus, WorkflowContext
from services.workflow_context.attribute_path import DEBUG_LOGS_METADATA_SUFFIX
from workflow_steps.notify_on_error.executor import execute


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    run.workflow_id = 42
    return run


def _workflow() -> MagicMock:
    workflow = MagicMock()
    workflow.id = 42
    workflow.name = "Backup Config"
    return workflow


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices)


def _error(step_id: str, message: str, node_id: str = "node-1") -> DeviceError:
    return DeviceError(node_id=node_id, step_id=step_id, code="boom", message=message)


def _patches(*, workflow_result=None, notification_repo=None):
    workflow_repo = MagicMock()
    workflow_repo.get_by_id.return_value = workflow_result
    notification_repo_instance = notification_repo or MagicMock()
    return (
        patch(
            "workflow_steps.common.notification_context.object_session",
            return_value=MagicMock(),
        ),
        patch(
            "workflow_steps.common.notification_context.WorkflowRepository",
            return_value=workflow_repo,
        ),
        patch(
            "workflow_steps.notify_on_error.executor.NotificationRepository",
            return_value=notification_repo_instance,
        ),
    )


class NotifyOnErrorExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_one_notification_per_device_error(self) -> None:
        device1 = DeviceContext(
            id="d1",
            name="router1",
            hostname="router1",
            status=DeviceStatus.FAILED,
            errors=[_error("run-command", "timeout")],
        )
        device2 = DeviceContext(
            id="d2",
            name="router2",
            hostname="router2",
            status=DeviceStatus.FAILED,
            errors=[_error("reachable", "unreachable")],
        )
        context = _context({"d1": device1, "d2": device2})

        notification_repo = MagicMock()
        notification_repo.create_batch.side_effect = lambda rows: [MagicMock() for _ in rows]

        session_p, workflow_p, notification_p = _patches(
            workflow_result=(_workflow(), "alice"),
            notification_repo=notification_repo,
        )
        with session_p, workflow_p, notification_p:
            outcomes = await execute(
                config={"message": "{device.name} failed at {error.step_id}: {error.message}"},
                context=context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-on-error-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")

        rows = notification_repo.create_batch.call_args.args[0]
        self.assertEqual(len(rows), 2)
        messages = {row["message"] for row in rows}
        self.assertEqual(
            messages,
            {
                "router1 failed at run-command: timeout",
                "router2 failed at reachable: unreachable",
            },
        )
        for row in rows:
            self.assertEqual(row["severity"], "error")
            self.assertEqual(row["workflow_id"], 42)
            self.assertEqual(row["workflow_owner_username"], "alice")

        debug_logs = outcomes[0].context.metadata[f"notify-on-error-1{DEBUG_LOGS_METADATA_SUFFIX}"]
        self.assertEqual(debug_logs["device_count"], 2)
        self.assertEqual(debug_logs["notification_count"], 2)

    async def test_multiple_errors_on_one_device_write_multiple_rows(self) -> None:
        device = DeviceContext(
            id="d1",
            name="router1",
            hostname="router1",
            status=DeviceStatus.FAILED,
            errors=[
                _error("reachable", "unreachable", node_id="node-a"),
                _error("run-command", "timeout", node_id="node-b"),
            ],
        )
        context = _context({"d1": device})

        notification_repo = MagicMock()
        notification_repo.create_batch.side_effect = lambda rows: [MagicMock() for _ in rows]

        session_p, workflow_p, notification_p = _patches(
            workflow_result=(_workflow(), "alice"),
            notification_repo=notification_repo,
        )
        with session_p, workflow_p, notification_p:
            outcomes = await execute(
                config={"message": "{device.name} @ {error.node_id}: {error.message}"},
                context=context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-on-error-1",
                device_sessions=MagicMock(),
            )

        rows = notification_repo.create_batch.call_args.args[0]
        self.assertEqual(len(rows), 2)
        messages = {row["message"] for row in rows}
        self.assertEqual(
            messages,
            {
                "router1 @ node-a: unreachable",
                "router1 @ node-b: timeout",
            },
        )
        self.assertEqual(outcomes[0].name, "success")

    async def test_device_with_no_errors_is_skipped(self) -> None:
        device_failed = DeviceContext(
            id="d1",
            name="router1",
            hostname="router1",
            status=DeviceStatus.FAILED,
            errors=[_error("run-command", "timeout")],
        )
        device_clean = DeviceContext(id="d2", name="router2", hostname="router2")
        context = _context({"d1": device_failed, "d2": device_clean})

        notification_repo = MagicMock()
        notification_repo.create_batch.side_effect = lambda rows: [MagicMock() for _ in rows]

        session_p, workflow_p, notification_p = _patches(
            workflow_result=(_workflow(), "alice"),
            notification_repo=notification_repo,
        )
        with session_p, workflow_p, notification_p:
            await execute(
                config={"message": "{device.name}: {error.message}"},
                context=context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-on-error-1",
                device_sessions=MagicMock(),
            )

        rows = notification_repo.create_batch.call_args.args[0]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["device_name"], "router1")

    async def test_no_devices_have_errors_writes_nothing(self) -> None:
        device = DeviceContext(id="d1", name="router1", hostname="router1")
        context = _context({"d1": device})

        notification_repo = MagicMock()
        notification_repo.create_batch.side_effect = lambda rows: [MagicMock() for _ in rows]

        session_p, workflow_p, notification_p = _patches(
            workflow_result=(_workflow(), "alice"),
            notification_repo=notification_repo,
        )
        with session_p, workflow_p, notification_p:
            outcomes = await execute(
                config={"message": "{device.name}: {error.message}"},
                context=context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-on-error-1",
                device_sessions=MagicMock(),
            )

        notification_repo.create_batch.assert_called_once_with([])
        self.assertEqual(outcomes[0].name, "success")

    async def test_empty_message_raises(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={"message": "  "},
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-on-error-1",
                device_sessions=MagicMock(),
            )

    async def test_missing_db_session_raises_runtime_error(self) -> None:
        with patch("workflow_steps.common.notification_context.object_session", return_value=None):
            with self.assertRaises(RuntimeError):
                await execute(
                    config={"message": "hello"},
                    context=_context({}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="notify-on-error-1",
                    device_sessions=MagicMock(),
                )

    async def test_workflow_not_found_raises_value_error(self) -> None:
        session_p, workflow_p, notification_p = _patches(workflow_result=None)
        with session_p, workflow_p, notification_p:
            with self.assertRaises(ValueError):
                await execute(
                    config={"message": "hello"},
                    context=_context({}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="notify-on-error-1",
                    device_sessions=MagicMock(),
                )


if __name__ == "__main__":
    unittest.main()
