"""Tests for batfish-acl-check executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.common.exceptions import BatfishAnswerFailedError
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_acl_check.executor import execute
from workflow_steps.common.batfish_context import store_batfish_snapshot

_SERVICE_FACTORY_TARGET = "workflow_steps.batfish_acl_check.executor.service_factory"

_BASE_CONFIG = {"node": "R1", "filter_name": "TEST-ACL", "dst_ips": "192.168.1.1"}


def _context_with_snapshot() -> WorkflowContext:
    context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
    return store_batfish_snapshot(
        context,
        connection=BatfishConnection(host="batfish", port=9996),
        network="manus-workflow-7",
        snapshot="run-42",
    )


class BatfishAclCheckExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, *, action: str, config: dict | None = None):
        run = MagicMock()
        run.id = 1
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.test_filters = AsyncMock(return_value=[{"Action": action}])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config=config or _BASE_CONFIG,
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        return outcomes, batfish

    async def test_permit_action_yields_permit_outcome(self) -> None:
        outcomes, _ = await self._run(action="PERMIT")
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "permit")

    async def test_deny_action_yields_deny_outcome(self) -> None:
        outcomes, _ = await self._run(action="DENY")
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "deny")

    async def test_empty_rows_raises_runtime_error(self) -> None:
        run = MagicMock()
        run.id = 1
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.test_filters = AsyncMock(return_value=[])
            service_factory_mock.get_batfish_app_service.return_value = batfish

            with self.assertRaises(RuntimeError):
                await execute(
                    config=_BASE_CONFIG,
                    context=_context_with_snapshot(),
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

    async def test_unknown_node_raises_value_error_not_internal_error(self) -> None:
        # Reproduces the reported bug: an unknown node/device makes Batfish
        # return a non-table Answer, which BatfishService now surfaces as
        # BatfishAnswerFailedError instead of crashing with an opaque
        # AttributeError. The executor must translate that into a ValueError
        # (a "configuration" category, user-facing message) rather than let
        # it propagate as an unclassified exception ("internal" category,
        # generic message).
        run = MagicMock()
        run.id = 1
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.test_filters = AsyncMock(
                side_effect=BatfishAnswerFailedError("testFilters", {"status": "FAILURE"})
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            with self.assertRaises(ValueError) as ctx:
                await execute(
                    config=_BASE_CONFIG,
                    context=_context_with_snapshot(),
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )
        self.assertIn("R1", str(ctx.exception))
        self.assertIn("TEST-ACL", str(ctx.exception))

    async def test_missing_node_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 1
        config = {**_BASE_CONFIG, "node": ""}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_missing_filter_name_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 1
        config = {**_BASE_CONFIG, "filter_name": ""}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_missing_dst_ips_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 1
        config = {**_BASE_CONFIG, "dst_ips": ""}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_explicit_source_and_network_bypasses_metadata(self) -> None:
        run = MagicMock()
        run.id = 1
        # Deliberately no metadata on this context -- proves the explicit
        # config path bypasses metadata entirely, not merely prefers it.
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")

        with (
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
            patch(
                "workflow_steps.common.batfish_context.object_session",
                return_value=MagicMock(),
            ),
            patch(
                "workflow_steps.common.batfish_context.BatfishSourceConfigService"
            ) as config_service_cls,
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="prod-host", port=9996
            )
            batfish = MagicMock()
            batfish.list_networks = AsyncMock(return_value=["manus-production"])
            batfish.test_filters = AsyncMock(return_value=[{"Action": "PERMIT"}])
            batfish.list_snapshots_with_metadata = AsyncMock(
                return_value=[
                    {"name": "run-99", "metadata": {"creationTimestamp": "2026-09-12T10:00:00Z"}}
                ]
            )
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={
                    **_BASE_CONFIG,
                    "batfish_source_id": "prod-batfish",
                    "network": "manus-production",
                },
                context=context,
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "permit")
        _, kwargs = batfish.test_filters.call_args
        self.assertEqual(kwargs["batfish_network"], "manus-production")
        self.assertEqual(kwargs["snapshot"], "run-99")

    async def test_missing_metadata_and_missing_config_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 1
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            service_factory_mock.get_batfish_app_service.return_value = MagicMock()
            with self.assertRaises(ValueError):
                await execute(
                    config={**_BASE_CONFIG, "batfish_source_id": "prod-batfish"},
                    context=WorkflowContext(run_id="run-uuid-1", workflow_id="7"),
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )


if __name__ == "__main__":
    unittest.main()
