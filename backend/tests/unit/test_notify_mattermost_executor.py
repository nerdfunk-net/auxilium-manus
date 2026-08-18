"""Tests for notify-mattermost executor (mocked Mattermost service layer, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import DeviceContext, WorkflowContext
from services.mattermost.common.exceptions import MattermostAPIError, MattermostValidationError
from services.mattermost.source_config_service import MattermostSourceNotFoundError
from workflow_steps.notify_mattermost.executor import execute

_BASE_CONFIG = {
    "mattermost_source_id": "lab-mm",
    "team_name": "networking",
    "channel_name": "alerts",
    "message": "Workflow finished: {device_count} device(s) ({devices})",
}


def _device(device_id: str, *, name: str | None = None, attribute_bags: dict | None = None):
    resolved_name = name or device_id
    return DeviceContext(
        id=device_id,
        name=resolved_name,
        hostname=resolved_name,
        attribute_bags=attribute_bags or {},
    )


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices)


def _client(*, channel_id: str = "chan123") -> MagicMock:
    client = MagicMock()
    client.get_channel_by_name = AsyncMock(return_value={"id": channel_id})
    client.create_post = AsyncMock(return_value={"id": "post123"})
    return client


def _patches(*, config_service: MagicMock | None = None, client: MagicMock | None = None):
    resolved_config_service = config_service or MagicMock()
    resolved_client = client or _client()
    return (
        patch(
            "workflow_steps.notify_mattermost.executor.object_session",
            return_value=MagicMock(),
        ),
        patch(
            "service_factory.build_mattermost_source_config_service",
            return_value=resolved_config_service,
        ),
        patch(
            "service_factory.get_mattermost_app_service",
            return_value=resolved_client,
        ),
    )


class NotifyMattermostExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_aggregated_message(self) -> None:
        device1 = _device("d1", name="router1")
        device2 = _device("d2", name="router2")
        context = _context({"d1": device1, "d2": device2})

        client = _client()
        session_p, config_p, client_p = _patches(client=client)
        with session_p, config_p, client_p:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-mattermost-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")

        client.get_channel_by_name.assert_awaited_once()
        call = client.create_post.call_args
        message = call.args[2]
        self.assertIn("2 device(s)", message)
        self.assertIn("router1", message)
        self.assertIn("router2", message)

    async def test_device_placeholder_resolves_against_first_device(self) -> None:
        device = _device(
            "d1", name="router1", attribute_bags={"nautobot": {"location": {"name": "core"}}}
        )
        context = _context({"d1": device})

        client = _client()
        session_p, config_p, client_p = _patches(client=client)
        config = {**_BASE_CONFIG, "message": "{device.name} at {nautobot.location.name}"}
        with session_p, config_p, client_p:
            await execute(
                config=config,
                context=context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-mattermost-1",
                device_sessions=MagicMock(),
            )

        message = client.create_post.call_args.args[2]
        self.assertEqual(message, "router1 at core")

    async def test_zero_devices_leaves_device_placeholder_unresolved(self) -> None:
        context = _context({})
        client = _client()
        session_p, config_p, client_p = _patches(client=client)
        config = {**_BASE_CONFIG, "message": "count={device_count} devices=({devices})"}
        with session_p, config_p, client_p:
            outcomes = await execute(
                config=config,
                context=context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-mattermost-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "success")
        message = client.create_post.call_args.args[2]
        self.assertEqual(message, "count=0 devices=()")

    async def test_channel_lookup_failure_returns_failure_outcome(self) -> None:
        client = _client()
        client.get_channel_by_name.side_effect = MattermostAPIError("channel not found")
        session_p, config_p, client_p = _patches(client=client)
        with session_p, config_p, client_p:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-mattermost-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "failure")
        client.create_post.assert_not_awaited()

    async def test_post_failure_returns_failure_outcome(self) -> None:
        client = _client()
        client.create_post.side_effect = MattermostAPIError("could not post")
        session_p, config_p, client_p = _patches(client=client)
        with session_p, config_p, client_p:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-mattermost-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "failure")

    async def test_missing_source_id_raises(self) -> None:
        config = {**_BASE_CONFIG, "mattermost_source_id": ""}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-mattermost-1",
                device_sessions=MagicMock(),
            )

    async def test_missing_team_name_raises(self) -> None:
        config = {**_BASE_CONFIG, "team_name": ""}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-mattermost-1",
                device_sessions=MagicMock(),
            )

    async def test_missing_channel_name_raises(self) -> None:
        config = {**_BASE_CONFIG, "channel_name": ""}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-mattermost-1",
                device_sessions=MagicMock(),
            )

    async def test_missing_message_raises(self) -> None:
        config = {**_BASE_CONFIG, "message": "  "}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="notify-mattermost-1",
                device_sessions=MagicMock(),
            )

    async def test_source_not_found_raises_value_error(self) -> None:
        config_service = MagicMock()
        config_service.resolve_credentials.side_effect = MattermostSourceNotFoundError("lab-mm")
        session_p, config_p, client_p = _patches(config_service=config_service)
        with session_p, config_p, client_p:
            with self.assertRaises(ValueError):
                await execute(
                    config=_BASE_CONFIG,
                    context=_context({}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="notify-mattermost-1",
                    device_sessions=MagicMock(),
                )

    async def test_source_validation_error_raises_value_error(self) -> None:
        config_service = MagicMock()
        config_service.resolve_credentials.side_effect = MattermostValidationError(
            "Mattermost source 'lab-mm' has no linked credential"
        )
        session_p, config_p, client_p = _patches(config_service=config_service)
        with session_p, config_p, client_p:
            with self.assertRaises(ValueError):
                await execute(
                    config=_BASE_CONFIG,
                    context=_context({}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="notify-mattermost-1",
                    device_sessions=MagicMock(),
                )

    async def test_missing_db_session_raises_runtime_error(self) -> None:
        with patch("workflow_steps.notify_mattermost.executor.object_session", return_value=None):
            with self.assertRaises(RuntimeError):
                await execute(
                    config=_BASE_CONFIG,
                    context=_context({}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="notify-mattermost-1",
                    device_sessions=MagicMock(),
                )


if __name__ == "__main__":
    unittest.main()
