"""Tests for parse-cisco-config executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from workflow_steps.parse_cisco_config.executor import execute

_RUNNING_CONFIG = """Current configuration : 543 bytes
!
hostname router1
!
interface GigabitEthernet0/1
 ip address 10.0.0.1 255.255.255.0
!
end
"""

_STARTUP_CONFIG = """Current configuration : 521 bytes
!
hostname router1-startup
!
interface GigabitEthernet0/1
 ip address 10.0.0.2 255.255.255.0
!
end
"""

# No platform banner line — undetectable without an explicit platform hint.
_NO_BANNER_CONFIG = """hostname router1
!
interface GigabitEthernet0/1
 ip address 10.0.0.1 255.255.255.0
!
end
"""


class ParseCiscoConfigExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_running_config_only(self) -> None:
        run = MagicMock()
        run.id = 1
        artifact_service = InMemoryArtifactService()
        running_ref = await artifact_service.store(
            content=_RUNNING_CONFIG,
            kind="running_config",
            device_id="device-1",
            run_id="run-1",
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
            running_config_ref=running_ref,
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})

        outcomes = await execute(
            config={"config_source": "running", "output_key": "cisco_config"},
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="parse-cisco-config-1",
        )

        self.assertEqual(len(outcomes), 1)
        success = outcomes[0].context.devices["device-1"]
        self.assertIn(Capability.PARSED, success.capabilities)
        entry = success.parsed["cisco_config"]
        self.assertEqual(entry["hostname"], "router1")
        self.assertEqual(entry["platform"], "IOS")

    async def test_parses_both_running_and_startup_nested(self) -> None:
        run = MagicMock()
        run.id = 1
        artifact_service = InMemoryArtifactService()
        running_ref = await artifact_service.store(
            content=_RUNNING_CONFIG, kind="running_config", device_id="device-1", run_id="run-1"
        )
        startup_ref = await artifact_service.store(
            content=_STARTUP_CONFIG, kind="startup_config", device_id="device-1", run_id="run-1"
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
            running_config_ref=running_ref,
            startup_config_ref=startup_ref,
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})

        outcomes = await execute(
            config={"config_source": "both", "output_key": "cisco_config"},
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="parse-cisco-config-1",
        )

        self.assertEqual(len(outcomes), 1)
        success = outcomes[0].context.devices["device-1"]
        entry = success.parsed["cisco_config"]
        self.assertEqual(entry["running"]["hostname"], "router1")
        self.assertEqual(entry["startup"]["hostname"], "router1-startup")

    async def test_missing_running_ref_fails_device(self) -> None:
        run = MagicMock()
        run.id = 1
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})

        outcomes = await execute(
            config={"config_source": "running", "output_key": "cisco_config"},
            context=context,
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="parse-cisco-config-1",
        )

        self.assertEqual(len(outcomes), 2)
        failed = outcomes[1].context.devices["device-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "config_error")

    async def test_both_mode_fails_whole_device_when_one_side_missing(self) -> None:
        run = MagicMock()
        run.id = 1
        artifact_service = InMemoryArtifactService()
        running_ref = await artifact_service.store(
            content=_RUNNING_CONFIG, kind="running_config", device_id="device-1", run_id="run-1"
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
            running_config_ref=running_ref,
            # No startup_config_ref.
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})

        outcomes = await execute(
            config={"config_source": "both", "output_key": "cisco_config"},
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="parse-cisco-config-1",
        )

        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0].context.devices, {})
        failed = outcomes[1].context.devices["device-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertNotIn("cisco_config", failed.parsed)

    async def test_network_driver_platform_hint_resolves_ambiguous_config(self) -> None:
        run = MagicMock()
        run.id = 1
        artifact_service = InMemoryArtifactService()
        running_ref = await artifact_service.store(
            content=_NO_BANNER_CONFIG,
            kind="running_config",
            device_id="device-1",
            run_id="run-1",
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
            running_config_ref=running_ref,
            network_driver="cisco_ios",
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})

        outcomes = await execute(
            config={"config_source": "running", "output_key": "cisco_config"},
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="parse-cisco-config-1",
        )

        self.assertEqual(len(outcomes), 1)
        success = outcomes[0].context.devices["device-1"]
        self.assertEqual(success.parsed["cisco_config"]["hostname"], "router1")

    async def test_without_network_driver_hint_ambiguous_config_fails(self) -> None:
        run = MagicMock()
        run.id = 1
        artifact_service = InMemoryArtifactService()
        running_ref = await artifact_service.store(
            content=_NO_BANNER_CONFIG,
            kind="running_config",
            device_id="device-1",
            run_id="run-1",
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
            running_config_ref=running_ref,
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})

        outcomes = await execute(
            config={"config_source": "running", "output_key": "cisco_config"},
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="parse-cisco-config-1",
        )

        self.assertEqual(len(outcomes), 2)
        failed = outcomes[1].context.devices["device-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
