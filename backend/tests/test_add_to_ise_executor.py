"""Tests for add-to-ise executor (mocked ISE service layer, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.ise.common.exceptions import ISEAPIError, ISEValidationError
from workflow_steps.add_to_ise.executor import execute
from workflow_steps.common.attribute_path import resolve_device_attribute

_BASE_CONFIG = {
    "ise_source_id": "lab-ise",
    "device_name": "router1",
    "ip_address": "10.10.10.1",
    "new_key": "s3cr3t",
}


def _device(
    device_id: str,
    *,
    name: str | None = None,
    attribute_bags: dict | None = None,
) -> DeviceContext:
    resolved_name = name or device_id
    return DeviceContext(
        id=device_id,
        name=resolved_name,
        hostname=resolved_name,
        source="nautobot",
        attribute_bags=attribute_bags or {},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices)


def _device_service() -> MagicMock:
    device_service = MagicMock()
    device_service.test_connection = AsyncMock(return_value={"total": 0})
    device_service.create_device = AsyncMock(
        return_value={"id": "ise-guid-1", "location": "https://ise/ers/config/networkdevice/ise-guid-1"}
    )
    return device_service


def _patches(device_service: MagicMock):
    source_config_service = MagicMock()
    source_config_service.resolve_credentials.return_value = MagicMock()
    return (
        patch(
            "workflow_steps.add_to_ise.executor.object_session",
            return_value=MagicMock(),
        ),
        patch(
            "service_factory.build_ise_source_config_service",
            return_value=source_config_service,
        ),
        patch(
            "service_factory.build_ise_network_device_service",
            return_value=device_service,
        ),
    )


class AddToIseExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_ise_source_id(self) -> None:
        config = {**_BASE_CONFIG, "ise_source_id": ""}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

    async def test_requires_device_name(self) -> None:
        config = {**_BASE_CONFIG, "device_name": ""}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

    async def test_requires_ip_address(self) -> None:
        config = {**_BASE_CONFIG, "ip_address": ""}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

    async def test_requires_new_key(self) -> None:
        config = {**_BASE_CONFIG, "new_key": ""}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

    async def test_no_devices_is_a_noop(self) -> None:
        device_service = _device_service()
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        device_service.test_connection.assert_not_called()

    async def test_unreachable_ise_returns_failure_outcome(self) -> None:
        device_service = _device_service()
        device_service.test_connection = AsyncMock(
            side_effect=ISEAPIError("ISE request timed out after 30 seconds")
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "failure")
        self.assertIn("lab-ise", outcomes[0].summary)
        self.assertIs(outcomes[0].context.devices["dev-1"].status, DeviceStatus.OK)

    async def test_literal_fields_create_device_with_defaults(self) -> None:
        device_service = _device_service()
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        device_service.create_device.assert_called_once_with(
            {
                "name": "router1",
                "NetworkDeviceIPList": [{"ipaddress": "10.10.10.1", "mask": 32}],
                "tacacsSettings": {"sharedSecret": "s3cr3t", "connectModeOptions": "OFF"},
            }
        )
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "tacacs.shared_secret"), "s3cr3t")
        self.assertEqual(resolve_device_attribute(updated, "ise.id"), "ise-guid-1")
        self.assertIn(Capability.ATTRIBUTES, updated.capabilities)
        self.assertEqual(outcomes[0].context.metadata["node-1.created_count"], 1)
        self.assertEqual(outcomes[0].context.metadata["node-1.failed_count"], 0)

    async def test_description_and_groups_included_when_set(self) -> None:
        device_service = _device_service()
        config = {
            **_BASE_CONFIG,
            "description": "testdevice",
            "device_groups": ["Location#All Locations", "  ", "Device Type#All Device Types"],
        }
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        device_service.create_device.assert_called_once_with(
            {
                "name": "router1",
                "NetworkDeviceIPList": [{"ipaddress": "10.10.10.1", "mask": 32}],
                "tacacsSettings": {"sharedSecret": "s3cr3t", "connectModeOptions": "OFF"},
                "description": "testdevice",
                "NetworkDeviceGroupList": [
                    "Location#All Locations",
                    "Device Type#All Device Types",
                ],
            }
        )

    async def test_path_expression_resolves_per_device(self) -> None:
        device_service = _device_service()
        config = {
            **_BASE_CONFIG,
            "device_name": "{name}",
            "ip_address": "{primary_ip4}",
            "new_key": "{custom.new_tacacs_key}",
        }
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=config,
                context=_context(
                    {
                        "dev-1": DeviceContext(
                            id="dev-1",
                            name="edge-router",
                            hostname="edge-router",
                            primary_ip4="10.0.0.5/32",
                            source="nautobot",
                            attribute_bags={"custom": {"new_tacacs_key": "from-path"}},
                            capabilities={Capability.IDENTITY},
                            status=DeviceStatus.OK,
                        )
                    }
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        (payload,), _ = device_service.create_device.call_args
        self.assertEqual(payload["name"], "edge-router")
        self.assertEqual(payload["NetworkDeviceIPList"][0]["ipaddress"], "10.0.0.5")
        self.assertEqual(payload["NetworkDeviceIPList"][0]["mask"], 32)
        self.assertEqual(payload["tacacsSettings"]["sharedSecret"], "from-path")
        self.assertEqual(outcomes[0].context.metadata["node-1.created_count"], 1)

    async def test_unresolved_device_name_marks_device_failed_but_step_succeeds(self) -> None:
        device_service = _device_service()
        config = {**_BASE_CONFIG, "device_name": "{missing.path}"}
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        device_service.create_device.assert_not_called()
        self.assertEqual(outcomes[0].name, "success")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "device_name_unresolved")
        self.assertEqual(outcomes[0].context.metadata["node-1.failed_count"], 1)

    async def test_unresolved_ip_address_marks_device_failed(self) -> None:
        device_service = _device_service()
        config = {**_BASE_CONFIG, "ip_address": "{missing.path}"}
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        device_service.create_device.assert_not_called()
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "ip_address_unresolved")

    async def test_default_ip_address_falls_back_to_nautobot_bag(self) -> None:
        """device.primary_ip4 is only set by inventory steps that fetch full
        device records (Get from Nautobot/Get from Git) — a device sourced via
        Get from List and enriched by Get Nautobot Attributes only has the IP
        nested in the nautobot attribute bag. The default {primary_ip4}
        expression must still resolve in that case."""
        device_service = _device_service()
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=_BASE_CONFIG | {"ip_address": "{primary_ip4}"},
                context=_context(
                    {
                        "dev-1": DeviceContext(
                            id="dev-1",
                            name="lab",
                            hostname="lab",
                            primary_ip4=None,
                            source="",
                            attribute_bags={
                                "nautobot": {"primary_ip4": {"address": "10.10.10.9/24"}}
                            },
                            capabilities={Capability.IDENTITY},
                            status=DeviceStatus.OK,
                        )
                    }
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        (payload,), _ = device_service.create_device.call_args
        self.assertEqual(payload["NetworkDeviceIPList"][0]["ipaddress"], "10.10.10.9")
        self.assertEqual(payload["NetworkDeviceIPList"][0]["mask"], 32)
        self.assertEqual(outcomes[0].context.metadata["node-1.created_count"], 1)

    async def test_unresolved_new_key_marks_device_failed(self) -> None:
        device_service = _device_service()
        config = {**_BASE_CONFIG, "new_key": "{missing.path}"}
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        device_service.create_device.assert_not_called()
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "tacacs_key_unresolved")

    async def test_create_rejected_marks_device_failed_but_step_succeeds(self) -> None:
        device_service = _device_service()
        device_service.create_device = AsyncMock(
            side_effect=ISEValidationError("device already exists")
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertEqual(outcomes[0].name, "success")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "ise_device_create_rejected")
        self.assertEqual(outcomes[0].context.metadata["node-1.failed_count"], 1)

    async def test_bare_api_error_mid_run_aborts_with_failure_outcome(self) -> None:
        device_service = _device_service()
        device_service.create_device = AsyncMock(
            side_effect=ISEAPIError("ISE ERS request failed with status 401")
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "failure")
        self.assertIn("lab-ise", outcomes[0].summary)

    async def test_invalid_device_groups_type_raises(self) -> None:
        config = {**_BASE_CONFIG, "device_groups": "not-a-list"}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

    async def test_cidr_suffixed_ip_address_is_normalized_to_bare_host(self) -> None:
        device_service = _device_service()
        config = {**_BASE_CONFIG, "ip_address": "10.10.10.5/24"}
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        (payload,), _ = device_service.create_device.call_args
        self.assertEqual(payload["NetworkDeviceIPList"][0]["ipaddress"], "10.10.10.5")
        self.assertEqual(payload["NetworkDeviceIPList"][0]["mask"], 32)

    async def test_invalid_ip_address_marks_device_failed_but_step_succeeds(self) -> None:
        device_service = _device_service()
        config = {**_BASE_CONFIG, "ip_address": "not-an-ip"}
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        device_service.create_device.assert_not_called()
        self.assertEqual(outcomes[0].name, "success")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "ip_address_invalid")
        self.assertEqual(outcomes[0].context.metadata["node-1.failed_count"], 1)


if __name__ == "__main__":
    unittest.main()
