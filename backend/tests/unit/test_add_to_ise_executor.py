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
from services.workflow_context.attribute_path import resolve_device_attribute
from workflow_steps.add_to_ise.executor import execute

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
        return_value={
            "id": "ise-guid-1",
            "location": "https://ise/ers/config/networkdevice/ise-guid-1",
        }
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
                device_sessions=MagicMock(),
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
                device_sessions=MagicMock(),
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
                device_sessions=MagicMock(),
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
                device_sessions=MagicMock(),
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
                device_sessions=MagicMock(),
            )

        self.assertEqual([o.name for o in outcomes], ["success", "exists"])
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
                device_sessions=MagicMock(),
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
                device_sessions=MagicMock(),
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
        # Both copies (tacacs bag and nested ise.tacacsSettings) are stored
        # sealed, not as raw cleartext strings — even though the ISE API call
        # above correctly received cleartext.
        from services.workflow_context.secret_fields import is_sealed_secret

        self.assertTrue(is_sealed_secret(updated.attribute_bags["tacacs"]["shared_secret"]))
        self.assertTrue(
            is_sealed_secret(updated.attribute_bags["ise"]["tacacsSettings"]["sharedSecret"])
        )

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
                device_sessions=MagicMock(),
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
                device_sessions=MagicMock(),
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
                device_sessions=MagicMock(),
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
                device_sessions=MagicMock(),
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
                device_sessions=MagicMock(),
            )

        (payload,), _ = device_service.create_device.call_args
        self.assertEqual(payload["NetworkDeviceIPList"][0]["ipaddress"], "10.10.10.9")
        self.assertEqual(payload["NetworkDeviceIPList"][0]["mask"], 24)
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
                device_sessions=MagicMock(),
            )

        device_service.create_device.assert_not_called()
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "tacacs_key_unresolved")

    async def test_create_rejected_marks_device_failed_but_step_succeeds(self) -> None:
        device_service = _device_service()
        device_service.create_device = AsyncMock(
            side_effect=ISEValidationError("Illegal IP Address")
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "success")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "ise_device_create_rejected")
        self.assertEqual(outcomes[0].context.metadata["node-1.failed_count"], 1)

    async def test_description_resolves_attribute_expression(self) -> None:
        device_service = _device_service()
        config = {**_BASE_CONFIG, "description": "{custom.note}"}
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            await execute(
                config=config,
                context=_context(
                    {
                        "dev-1": _device(
                            "dev-1",
                            name="router1",
                            attribute_bags={"custom": {"note": "Lab router"}},
                        ),
                        "dev-2": _device("dev-2", name="router2"),
                    }
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        payloads = [call.args[0] for call in device_service.create_device.call_args_list]
        self.assertEqual(payloads[0]["description"], "Lab router")
        # Unresolvable optional description: device is still created, without one.
        self.assertNotIn("description", payloads[1])

    async def _created_mask(self, *, ip: str, netmask_override: str | None = None) -> int:
        device_service = _device_service()
        config = {**_BASE_CONFIG, "ip_address": ip}
        if netmask_override is not None:
            config["netmask_override"] = netmask_override
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        entry = device_service.create_device.call_args.args[0]["NetworkDeviceIPList"][0]
        self.assertEqual(entry["ipaddress"], ip.split("/")[0])
        return entry["mask"]

    async def test_mask_taken_from_ip_address_suffix(self) -> None:
        self.assertEqual(await self._created_mask(ip="192.168.178.240/24"), 24)

    async def test_mask_defaults_to_32_without_suffix(self) -> None:
        self.assertEqual(await self._created_mask(ip="192.168.178.240"), 32)

    async def test_netmask_override_wins_over_suffix(self) -> None:
        self.assertEqual(
            await self._created_mask(ip="192.168.178.240/24", netmask_override="32"), 32
        )
        self.assertEqual(
            await self._created_mask(ip="192.168.178.240", netmask_override="/28"), 28
        )

    async def test_blank_netmask_override_falls_back_to_suffix(self) -> None:
        self.assertEqual(
            await self._created_mask(ip="192.168.178.240/24", netmask_override="  "), 24
        )

    async def test_invalid_netmask_override_raises(self) -> None:
        for bad in ("abc", "-1", "129"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    await execute(
                        config={**_BASE_CONFIG, "netmask_override": bad},
                        context=_context({"dev-1": _device("dev-1", name="router1")}),
                        run=_run(),
                        artifact_service=MagicMock(),
                        node_id="node-1",
                        device_sessions=MagicMock(),
                    )

    async def test_mask_too_long_for_ipv4_fails_device(self) -> None:
        device_service = _device_service()
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={**_BASE_CONFIG, "netmask_override": "64"},
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        device_service.create_device.assert_not_called()
        failed = {o.name: o for o in outcomes}["success"].context.devices["dev-1"]
        self.assertEqual(failed.errors[-1].code, "netmask_invalid")

    async def test_duplicate_name_routes_device_to_exists_outcome(self) -> None:
        device_service = _device_service()
        device_service.create_device = AsyncMock(
            side_effect=[
                ISEValidationError("Network Device Create failed: Device Name Already Exists"),
                {"id": "ise-2"},
            ]
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=_context(
                    {
                        "dev-1": _device("dev-1", name="router1"),
                        "dev-2": _device("dev-2", name="router2"),
                    }
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(by_name), {"success", "exists"})
        self.assertEqual(list(by_name["exists"].context.devices), ["dev-1"])
        self.assertEqual(list(by_name["success"].context.devices), ["dev-2"])
        self.assertIs(by_name["exists"].context.devices["dev-1"].status, DeviceStatus.OK)
        self.assertEqual(by_name["success"].context.metadata["node-1.exists_count"], 1)
        self.assertEqual(by_name["success"].context.metadata["node-1.created_count"], 1)

    async def test_request_and_response_recorded_in_requests_not_bags(self) -> None:
        device_service = _device_service()
        device_service.create_device = AsyncMock(
            side_effect=[
                {"id": "ise-1", "location": "https://ise/x"},
                ISEValidationError("Device Name Already Exists"),
                ISEValidationError("Illegal IP Address"),
            ]
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=_context(
                    {
                        "a": _device("a", name="r1"),
                        "b": _device("b", name="r2"),
                        "c": _device("c", name="r3"),
                    }
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        by_name = {o.name: o for o in outcomes}
        created = by_name["success"].context.devices["a"]
        (record,) = created.requests["node-1"]
        self.assertEqual((record.method, record.endpoint), ("POST", "/ers/config/networkdevice"))
        self.assertTrue(record.ok)
        self.assertEqual(record.response["id"], "ise-1")
        body = record.request["NetworkDevice"]
        self.assertEqual(body["name"], "router1")
        self.assertEqual(body["tacacsSettings"]["sharedSecret"], "***REDACTED***")
        self.assertNotIn("add_to_ise", created.attribute_bags)

        exists = by_name["exists"].context.devices["b"]
        self.assertEqual(
            exists.requests["node-1"][0].response, {"error": "Device Name Already Exists"}
        )
        self.assertFalse(exists.requests["node-1"][0].ok)
        self.assertNotIn("ise", exists.attribute_bags)

        rejected = by_name["success"].context.devices["c"]
        self.assertEqual(rejected.requests["node-1"][0].response, {"error": "Illegal IP Address"})

        dumped_requests = repr([d.model_dump()["requests"] for d in (created, exists, rejected)])
        self.assertNotIn("s3cr3t", dumped_requests)

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
                device_sessions=MagicMock(),
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
                device_sessions=MagicMock(),
            )

    async def test_cidr_suffixed_ip_address_is_split_into_host_and_mask(self) -> None:
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
                device_sessions=MagicMock(),
            )

        (payload,), _ = device_service.create_device.call_args
        self.assertEqual(payload["NetworkDeviceIPList"][0]["ipaddress"], "10.10.10.5")
        self.assertEqual(payload["NetworkDeviceIPList"][0]["mask"], 24)

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
                device_sessions=MagicMock(),
            )

        device_service.create_device.assert_not_called()
        self.assertEqual(outcomes[0].name, "success")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "ip_address_invalid")
        self.assertEqual(outcomes[0].context.metadata["node-1.failed_count"], 1)


if __name__ == "__main__":
    unittest.main()
