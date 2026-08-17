"""Tests for notify executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from models.workflow_context import DeviceContext, WorkflowContext
from services.workflow_context.attribute_path import DEBUG_LOGS_METADATA_SUFFIX
from workflow_steps.notify.executor import execute


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


def _patches(*, workflow_result=None, notification_repo=None):
    workflow_repo = MagicMock()
    workflow_repo.get_by_id.return_value = workflow_result
    notification_repo_instance = notification_repo or MagicMock()
    return (
        patch(
            "workflow_steps.notify.executor.object_session",
            return_value=MagicMock(),
        ),
        patch(
            "workflow_steps.notify.executor.WorkflowRepository",
            return_value=workflow_repo,
        ),
        patch(
            "workflow_steps.notify.executor.NotificationRepository",
            return_value=notification_repo_instance,
        ),
    )


class NotifyExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_one_notification_per_device(self) -> None:
        device1 = DeviceContext(id="d1", name="router1", hostname="router1")
        device2 = DeviceContext(id="d2", name="router2", hostname="router2")
        context = _context({"d1": device1, "d2": device2})

        notification_repo = MagicMock()
        notification_repo.create_batch.side_effect = lambda rows: [MagicMock() for _ in rows]

        session_p, workflow_p, notification_p = _patches(
            workflow_result=(_workflow(), "alice"),
            notification_repo=notification_repo,
        )
        with session_p, workflow_p, notification_p:
            outcomes = await execute(
                config={
                    "message": "Could not get config from device {device.name}",
                    "severity": "warning",
                },
                context=context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")

        rows = notification_repo.create_batch.call_args.args[0]
        self.assertEqual(len(rows), 2)
        names = {row["device_name"] for row in rows}
        self.assertEqual(names, {"router1", "router2"})
        for row in rows:
            self.assertEqual(row["workflow_id"], 42)
            self.assertEqual(row["workflow_name"], "Backup Config")
            self.assertEqual(row["workflow_owner_username"], "alice")
            self.assertEqual(row["severity"], "warning")
            self.assertIn("Could not get config from device", row["message"])

        debug_logs = outcomes[0].context.metadata[f"notify-1{DEBUG_LOGS_METADATA_SUFFIX}"]
        self.assertEqual(debug_logs["device_count"], 2)

    async def test_unresolved_placeholder_renders_empty(self) -> None:
        device = DeviceContext(id="d1", name="router1", hostname="router1")
        context = _context({"d1": device})

        notification_repo = MagicMock()
        notification_repo.create_batch.side_effect = lambda rows: [MagicMock() for _ in rows]

        session_p, workflow_p, notification_p = _patches(
            workflow_result=(_workflow(), "alice"),
            notification_repo=notification_repo,
        )
        with session_p, workflow_p, notification_p:
            await execute(
                config={"message": "key={tacacs.shared_secret}", "severity": "info"},
                context=context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-1",
                device_sessions=MagicMock(),
            )

        rows = notification_repo.create_batch.call_args.args[0]
        self.assertEqual(rows[0]["message"], "key=")

    async def test_empty_message_raises(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={"message": "  ", "severity": "info"},
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-1",
                device_sessions=MagicMock(),
            )

    async def test_invalid_severity_raises(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={"message": "hello", "severity": "critical"},
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-1",
                device_sessions=MagicMock(),
            )

    async def test_no_devices_writes_nothing(self) -> None:
        notification_repo = MagicMock()
        notification_repo.create_batch.side_effect = lambda rows: [MagicMock() for _ in rows]

        session_p, workflow_p, notification_p = _patches(
            workflow_result=(_workflow(), "alice"),
            notification_repo=notification_repo,
        )
        with session_p, workflow_p, notification_p:
            outcomes = await execute(
                config={"message": "hello", "severity": "info"},
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-1",
                device_sessions=MagicMock(),
            )

        notification_repo.create_batch.assert_called_once_with([])
        self.assertEqual(outcomes[0].name, "success")

    async def test_missing_db_session_raises_runtime_error(self) -> None:
        with patch("workflow_steps.notify.executor.object_session", return_value=None):
            with self.assertRaises(RuntimeError):
                await execute(
                    config={"message": "hello", "severity": "info"},
                    context=_context({}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="notify-1",
                    device_sessions=MagicMock(),
                )

    async def test_workflow_not_found_raises_value_error(self) -> None:
        session_p, workflow_p, notification_p = _patches(workflow_result=None)
        with session_p, workflow_p, notification_p:
            with self.assertRaises(ValueError):
                await execute(
                    config={"message": "hello", "severity": "info"},
                    context=_context({}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="notify-1",
                    device_sessions=MagicMock(),
                )


if __name__ == "__main__":
    unittest.main()
