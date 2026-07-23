"""Tests for add-to-nautobot executor (mocked Nautobot service layer, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from workflow_steps.add_to_nautobot.config import get_config
from workflow_steps.add_to_nautobot.executor import execute

_BASE_CONFIG = {
    **get_config(),
    "nautobot_source_id": "prod-lab",
    "device_fields": {
        "name": {"enabled": True, "value": "{name}"},
        "role": {"enabled": True, "value": "access-switch"},
        "status": {"enabled": True, "value": "active"},
        "location": {"enabled": True, "value": "dc1"},
        "device_type": {"enabled": True, "value": "C9300-24T"},
    },
}


def _device(
    device_id: str, *, name: str | None = None, nautobot_bag: dict | None = None
) -> DeviceContext:
    resolved_name = name or device_id
    return DeviceContext(
        id=device_id,
        name=resolved_name,
        hostname=resolved_name,
        source="list",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        attribute_bags={"nautobot": nautobot_bag} if nautobot_bag is not None else {},
    )


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices)


def _setting() -> MagicMock:
    setting = MagicMock()
    setting.value = {"url": "https://nautobot.lab", "token": "tok"}
    return setting


def _creation_service(create_device: AsyncMock) -> MagicMock:
    instance = MagicMock()
    instance.create_device = create_device
    return instance


def _patches(*, setting=None, creation_service_instance=None):
    settings_repo = MagicMock()
    settings_repo.get_by_key.return_value = setting
    return (
        patch(
            "workflow_steps.add_to_nautobot.executor.object_session",
            return_value=MagicMock(),
        ),
        patch(
            "workflow_steps.add_to_nautobot.executor.SettingsRepository",
            return_value=settings_repo,
        ),
        patch(
            "service_factory.credentials_from_connection",
            return_value=MagicMock(),
        ),
        patch(
            "service_factory.get_nautobot_app_service",
            return_value=MagicMock(),
        ),
        patch(
            "workflow_steps.add_to_nautobot.executor.DeviceCreationService",
            return_value=creation_service_instance,
        ),
    )


class AddToNautobotExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_nautobot_source_id(self) -> None:
        config = {**_BASE_CONFIG, "nautobot_source_id": ""}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

    async def test_requires_devices_in_context(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config=_BASE_CONFIG,
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

    async def test_missing_source_setting_raises(self) -> None:
        p1, p2, p3, p4, p5 = _patches(setting=None, creation_service_instance=MagicMock())
        with p1, p2, p3, p4, p5:
            with self.assertRaises(ValueError):
                await execute(
                    config=_BASE_CONFIG,
                    context=_context({"dev-1": _device("dev-1", name="router1")}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="node-1",
                )

    async def test_success_path_creates_device_and_enriches_context(self) -> None:
        create_device = AsyncMock(
            return_value={
                "success": True,
                "dry_run": False,
                "device_id": "nb-device-uuid-1",
                "device_name": "router1",
                "device": {"id": "nb-device-uuid-1", "name": "router1"},
                "interfaces_created": 0,
                "interfaces_failed": 0,
                "warnings": [],
                "errors": [],
            }
        )
        p1, p2, p3, p4, p5 = _patches(
            setting=_setting(),
            creation_service_instance=_creation_service(create_device),
        )
        with p1, p2, p3, p4, p5:
            outcomes = await execute(
                config=_BASE_CONFIG,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.id, "nb-device-uuid-1")
        self.assertEqual(updated.source, "nautobot")
        self.assertIs(updated.status, DeviceStatus.OK)
        self.assertEqual(updated.attribute_bags["nautobot"]["id"], "nb-device-uuid-1")
        self.assertIn(Capability.ATTRIBUTES, updated.capabilities)

        create_device.assert_awaited_once()
        request = create_device.await_args.args[0]
        self.assertEqual(request.name, "router1")
        self.assertEqual(request.role, "access-switch")
        self.assertEqual(request.status, "active")
        self.assertEqual(request.location, "dc1")
        self.assertEqual(request.device_type, "C9300-24T")

    async def test_dry_run_success_also_marks_attributes_capability(self) -> None:
        create_device = AsyncMock(
            return_value={"success": True, "dry_run": True, "errors": []}
        )
        config = {**_BASE_CONFIG, "dry_run": True}
        p1, p2, p3, p4, p5 = _patches(
            setting=_setting(),
            creation_service_instance=_creation_service(create_device),
        )
        with p1, p2, p3, p4, p5:
            outcomes = await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertIs(updated.status, DeviceStatus.OK)
        self.assertIn(Capability.ATTRIBUTES, updated.capabilities)

    async def test_custom_fields_source_all_sends_every_bag_field(self) -> None:
        create_device = AsyncMock(
            return_value={
                "success": True,
                "dry_run": False,
                "device_id": "nb-device-uuid-3",
                "device_name": "router1",
                "device": {"id": "nb-device-uuid-3"},
                "interfaces_created": 0,
                "interfaces_failed": 0,
                "warnings": [],
                "errors": [],
            }
        )
        config = {**_BASE_CONFIG, "custom_fields_source": "nautobot_origin"}
        device = _device(
            "dev-1",
            name="router1",
            nautobot_bag={"custom_fields": {"net": "lab", "mounts": "rack1", "empty": None}},
        )
        p1, p2, p3, p4, p5 = _patches(
            setting=_setting(),
            creation_service_instance=_creation_service(create_device),
        )
        with p1, p2, p3, p4, p5:
            await execute(
                config=config,
                context=_context({"dev-1": device}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        request = create_device.await_args.args[0]
        self.assertEqual(request.custom_fields, {"net": "lab", "mounts": "rack1"})

    async def test_custom_fields_source_all_varies_per_device(self) -> None:
        create_device = AsyncMock(
            return_value={
                "success": True,
                "dry_run": False,
                "device_id": "nb-device-uuid-4",
                "device_name": "router",
                "device": {"id": "nb-device-uuid-4"},
                "interfaces_created": 0,
                "interfaces_failed": 0,
                "warnings": [],
                "errors": [],
            }
        )
        config = {**_BASE_CONFIG, "custom_fields_source": "nautobot_origin"}
        device_a = _device("dev-a", name="a", nautobot_bag={"custom_fields": {"net": "lab"}})
        device_b = _device("dev-b", name="b", nautobot_bag={"custom_fields": {"site": "hq"}})
        p1, p2, p3, p4, p5 = _patches(
            setting=_setting(),
            creation_service_instance=_creation_service(create_device),
        )
        with p1, p2, p3, p4, p5:
            await execute(
                config=config,
                context=_context({"dev-a": device_a, "dev-b": device_b}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        payloads = {
            call.args[0].name: call.args[0].custom_fields
            for call in create_device.await_args_list
        }
        self.assertEqual(payloads["a"], {"net": "lab"})
        self.assertEqual(payloads["b"], {"site": "hq"})

    async def test_interfaces_source_all_reads_bag_with_multiple_ips(self) -> None:
        create_device = AsyncMock(
            return_value={
                "success": True,
                "dry_run": False,
                "device_id": "nb-device-uuid-5",
                "device_name": "router1",
                "device": {"id": "nb-device-uuid-5"},
                "interfaces_created": 2,
                "interfaces_failed": 0,
                "warnings": [],
                "errors": [],
            }
        )
        config = {**_BASE_CONFIG, "interfaces_source": "nautobot_origin"}
        device = _device(
            "dev-1",
            name="router1",
            nautobot_bag={
                "interfaces": [
                    {
                        "name": "Loopback0",
                        "type": "VIRTUAL",
                        "status": {"name": "Active"},
                        "ip_addresses": [
                            {"address": "10.0.0.1/32"},
                            {"address": "10.0.0.2"},
                        ],
                    },
                    {"name": "Ethernet0/1", "status": "Active"},
                ]
            },
        )
        p1, p2, p3, p4, p5 = _patches(
            setting=_setting(),
            creation_service_instance=_creation_service(create_device),
        )
        with p1, p2, p3, p4, p5:
            await execute(
                config=config,
                context=_context({"dev-1": device}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        request = create_device.await_args.args[0]
        self.assertEqual(len(request.interfaces), 2)
        loopback = next(i for i in request.interfaces if i["name"] == "Loopback0")
        self.assertEqual(loopback["type"], "VIRTUAL")
        self.assertEqual(loopback["status"], "Active")
        self.assertEqual(
            loopback["ip_addresses"],
            [
                {"address": "10.0.0.1/32", "namespace": "Global"},
                {"address": "10.0.0.2/24", "namespace": "Global"},
            ],
        )
        eth = next(i for i in request.interfaces if i["name"] == "Ethernet0/1")
        self.assertEqual(eth["status"], "Active")
        self.assertNotIn("ip_addresses", eth)

    async def test_interfaces_source_all_empty_bag_creates_no_interfaces(self) -> None:
        create_device = AsyncMock(
            return_value={
                "success": True,
                "dry_run": False,
                "device_id": "nb-device-uuid-6",
                "device_name": "router1",
                "device": {"id": "nb-device-uuid-6"},
                "interfaces_created": 0,
                "interfaces_failed": 0,
                "warnings": [],
                "errors": [],
            }
        )
        config = {**_BASE_CONFIG, "interfaces_source": "nautobot_origin"}
        p1, p2, p3, p4, p5 = _patches(
            setting=_setting(),
            creation_service_instance=_creation_service(create_device),
        )
        with p1, p2, p3, p4, p5:
            await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        request = create_device.await_args.args[0]
        self.assertEqual(request.interfaces, [])

    async def test_invalid_custom_fields_source_raises(self) -> None:
        config = {**_BASE_CONFIG, "custom_fields_source": "bogus"}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

    async def test_invalid_interfaces_source_raises(self) -> None:
        config = {**_BASE_CONFIG, "interfaces_source": "bogus"}
        with self.assertRaises(ValueError):
            await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

    async def test_missing_required_field_fails_only_that_device(self) -> None:
        create_device = AsyncMock(
            return_value={
                "success": True,
                "dry_run": False,
                "device_id": "nb-device-uuid-2",
                "device_name": "router2",
                "device": {"id": "nb-device-uuid-2", "name": "router2"},
                "interfaces_created": 0,
                "interfaces_failed": 0,
                "warnings": [],
                "errors": [],
            }
        )
        config = {
            **_BASE_CONFIG,
            "device_fields": {
                **_BASE_CONFIG["device_fields"],
                "role": {"enabled": True, "value": ""},
            },
        }
        p1, p2, p3, p4, p5 = _patches(
            setting=_setting(),
            creation_service_instance=_creation_service(create_device),
        )
        with p1, p2, p3, p4, p5:
            outcomes = await execute(
                config=config,
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 2)
        names = {outcome.name for outcome in outcomes}
        self.assertEqual(names, {"success", "failure"})
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        failed = failure_outcome.context.devices["dev-1"]
        self.assertIs(failed.status, DeviceStatus.FAILED)
        self.assertIn("role", failed.errors[-1].message)
        create_device.assert_not_awaited()

    async def test_create_device_exception_fails_only_that_device(self) -> None:
        create_device = AsyncMock(side_effect=RuntimeError("Nautobot returned 400"))
        p1, p2, p3, p4, p5 = _patches(
            setting=_setting(),
            creation_service_instance=_creation_service(create_device),
        )
        with p1, p2, p3, p4, p5:
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
            )

        # Both devices attempt creation and both fail identically here since the
        # mock always raises; assert the step still returns without raising and
        # marks every failed device, rather than aborting the whole run. The
        # success outcome is still emitted (empty devices), same as
        # update-nautobot-device.
        names = {outcome.name for outcome in outcomes}
        self.assertEqual(names, {"success", "failure"})
        success_outcome = next(o for o in outcomes if o.name == "success")
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        self.assertEqual(len(success_outcome.context.devices), 0)
        self.assertEqual(len(failure_outcome.context.devices), 2)
        for device in failure_outcome.context.devices.values():
            self.assertIs(device.status, DeviceStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
