"""Tests for batfish-acl-check executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import WorkflowContext
from services.artifacts import InMemoryArtifactService
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


if __name__ == "__main__":
    unittest.main()
