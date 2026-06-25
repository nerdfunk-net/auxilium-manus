"""Tests for route-on-attribute executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.route_on_attribute.executor import execute


def _device(
    device_id: str,
    *,
    network_driver: str | None = None,
    attribute_bags: dict | None = None,
) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        network_driver=network_driver,
        attribute_bags=attribute_bags or {},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


class RouteOnAttributeExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_splits_devices_by_network_driver(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "ios-1": _device("ios-1", network_driver="cisco_ios"),
                "nxos-1": _device("nxos-1", network_driver="cisco_nxos"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "device.network_driver",
                "routes": [
                    {"outcome": "ios", "values": ["cisco_ios", "ios"]},
                    {"outcome": "nxos", "values": ["cisco_nxos", "nxos"]},
                ],
                "default_outcome": "unmatched",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-1",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(set(by_name), {"ios", "nxos", "unmatched"})
        self.assertEqual(list(by_name["ios"].context.devices), ["ios-1"])
        self.assertEqual(list(by_name["nxos"].context.devices), ["nxos-1"])
        self.assertEqual(by_name["unmatched"].context.devices, {})

    async def test_routes_by_nautobot_attribute(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "sw-1": _device(
                    "sw-1",
                    attribute_bags={"nautobot": {"role": {"name": "access-switch"}}},
                ),
                "rt-1": _device(
                    "rt-1",
                    attribute_bags={"nautobot": {"role": {"name": "core-router"}}},
                ),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "nautobot.role.name",
                "routes": [
                    {"outcome": "access", "values": ["access-switch"]},
                    {"outcome": "core", "values": ["core-router"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-2",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["access"].context.devices), ["sw-1"])
        self.assertEqual(list(by_name["core"].context.devices), ["rt-1"])

    async def test_default_outcome_catches_unmatched_devices(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "junos-1": _device("junos-1", network_driver="junos"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "network_driver",
                "routes": [{"outcome": "ios", "values": ["cisco_ios"]}],
                "default_outcome": "other",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-3",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(by_name["ios"].context.devices, {})
        self.assertEqual(list(by_name["other"].context.devices), ["junos-1"])

    async def test_fails_when_unmatched_without_default(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "junos-1": _device("junos-1", network_driver="junos"),
            },
        )

        with self.assertRaises(ValueError):
            await execute(
                config={
                    "attribute_path": "network_driver",
                    "routes": [{"outcome": "ios", "values": ["cisco_ios"]}],
                },
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="route-4",
            )

    async def test_first_matching_route_wins(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "ios-1": _device("ios-1", network_driver="cisco_ios"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "network_driver",
                "routes": [
                    {"outcome": "primary", "values": ["cisco_ios", "ios"]},
                    {"outcome": "secondary", "values": ["cisco_ios"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-5",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["primary"].context.devices), ["ios-1"])
        self.assertEqual(by_name["secondary"].context.devices, {})


if __name__ == "__main__":
    unittest.main()
