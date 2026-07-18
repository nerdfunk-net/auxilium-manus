"""Tests for update-ise-tacacs-key executor (mocked ISE service layer, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError
from workflow_steps.common.attribute_path import resolve_device_attribute
from workflow_steps.update_ise_tacacs_key.executor import execute


def _device(
    device_id: str,
    *,
    name: str | None = None,
    source: str = "",
    attribute_bags: dict | None = None,
) -> DeviceContext:
    resolved_name = name or device_id
    return DeviceContext(
        id=device_id,
        name=resolved_name,
        hostname=resolved_name,
        source=source,
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
    """A MagicMock ISENetworkDeviceService with test_connection and get_device
    pre-mocked to succeed, since execute() does a pre-flight connectivity
    check and always re-fetches the current device before updating it."""
    device_service = MagicMock()
    device_service.test_connection = AsyncMock(return_value={"total": 0})
    device_service.get_device = AsyncMock(
        return_value={"NetworkDevice": {"tacacsSettings": {"enableKeyWrap": False}}}
    )
    device_service.update_device = AsyncMock(return_value={"NetworkDevice": {}})
    return device_service


def _patches(device_service: MagicMock):
    source_config_service = MagicMock()
    source_config_service.resolve_credentials.return_value = MagicMock()
    return (
        patch(
            "workflow_steps.update_ise_tacacs_key.executor.object_session",
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


class UpdateIseTacacsKeyExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_ise_source_id(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={"new_key": "s3cr3t"},
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

    async def test_requires_new_key(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={"ise_source_id": "lab-ise"},
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
                config={"ise_source_id": "lab-ise", "new_key": "s3cr3t"},
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
                config={"ise_source_id": "lab-ise", "new_key": "s3cr3t"},
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "failure")
        self.assertIn("lab-ise", outcomes[0].summary)
        self.assertIs(outcomes[0].context.devices["dev-1"].status, DeviceStatus.OK)

    async def test_literal_key_updates_device_preserving_other_tacacs_settings(self) -> None:
        device_service = _device_service()
        device_service.get_device = AsyncMock(
            return_value={
                "NetworkDevice": {
                    "tacacsSettings": {
                        "sharedSecret": "old-secret",
                        "enableKeyWrap": True,
                        "connectModeOptions": "OFF",
                    }
                }
            }
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={"ise_source_id": "lab-ise", "new_key": "new-secret"},
                context=_context(
                    {"dev-1": _device("dev-1", name="router1", source="ise")}
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        device_service.get_device_by_name.assert_not_called()
        device_service.update_device.assert_called_once_with(
            "dev-1",
            {
                "tacacsSettings": {
                    "sharedSecret": "new-secret",
                    "enableKeyWrap": True,
                    "connectModeOptions": "OFF",
                }
            },
        )
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "tacacs.shared_secret"), "new-secret")
        self.assertIn(Capability.ATTRIBUTES, updated.capabilities)
        self.assertEqual(outcomes[0].context.metadata["node-1.updated_count"], 1)
        self.assertEqual(outcomes[0].context.metadata["node-1.failed_count"], 0)

    async def test_path_expression_resolves_per_device(self) -> None:
        device_service = _device_service()
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={"ise_source_id": "lab-ise", "new_key": "{custom.new_tacacs_key}"},
                context=_context(
                    {
                        "dev-1": _device(
                            "dev-1",
                            name="router1",
                            source="ise",
                            attribute_bags={"custom": {"new_tacacs_key": "from-path"}},
                        )
                    }
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        (call_device_id, call_payload), _ = device_service.update_device.call_args
        self.assertEqual(call_device_id, "dev-1")
        self.assertEqual(call_payload["tacacsSettings"]["sharedSecret"], "from-path")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "tacacs.shared_secret"), "from-path")

    async def test_unresolved_path_marks_device_failed_but_step_succeeds(self) -> None:
        device_service = _device_service()
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={"ise_source_id": "lab-ise", "new_key": "{custom.missing}"},
                context=_context({"dev-1": _device("dev-1", name="router1", source="ise")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        device_service.update_device.assert_not_called()
        self.assertEqual(outcomes[0].name, "success")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "tacacs_key_unresolved")
        self.assertEqual(outcomes[0].context.metadata["node-1.failed_count"], 1)

    async def test_ise_sourced_device_trusts_device_id(self) -> None:
        device_service = _device_service()
        device_service.get_device_by_name = AsyncMock(side_effect=Exception("should not be called"))
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            await execute(
                config={"ise_source_id": "lab-ise", "new_key": "s3cr3t"},
                context=_context({"dev-1": _device("dev-1", name="router1", source="ise")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        device_service.get_device_by_name.assert_not_called()
        device_service.get_device.assert_called_once_with("dev-1")

    async def test_non_ise_device_resolves_by_name(self) -> None:
        device_service = _device_service()
        device_service.get_device_by_name = AsyncMock(
            return_value={"NetworkDevice": {"id": "ise-guid-1"}}
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={"ise_source_id": "lab-ise", "new_key": "s3cr3t"},
                context=_context({"dev-1": _device("dev-1", name="router1", source="nautobot")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        device_service.get_device_by_name.assert_called_once_with("router1")
        device_service.update_device.assert_called_once()
        (call_device_id, _), _ = device_service.update_device.call_args
        self.assertEqual(call_device_id, "ise-guid-1")
        self.assertEqual(outcomes[0].context.metadata["node-1.updated_count"], 1)

    async def test_device_not_found_by_name_marks_failed_but_step_succeeds(self) -> None:
        device_service = _device_service()
        device_service.get_device_by_name = AsyncMock(
            side_effect=ISENotFoundError("ISE resource not found")
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={"ise_source_id": "lab-ise", "new_key": "s3cr3t"},
                context=_context({"dev-1": _device("dev-1", name="router1", source="nautobot")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertEqual(outcomes[0].name, "success")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "ise_device_not_found")

    async def test_update_rejected_marks_device_failed_but_step_succeeds(self) -> None:
        device_service = _device_service()
        device_service.update_device = AsyncMock(
            side_effect=ISEValidationError("invalid tacacs settings")
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={"ise_source_id": "lab-ise", "new_key": "s3cr3t"},
                context=_context({"dev-1": _device("dev-1", name="router1", source="ise")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertEqual(outcomes[0].name, "success")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "tacacs_key_update_rejected")

    async def test_bare_api_error_mid_run_aborts_with_failure_outcome(self) -> None:
        device_service = _device_service()
        device_service.update_device = AsyncMock(
            side_effect=ISEAPIError("ISE ERS request failed with status 401")
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={"ise_source_id": "lab-ise", "new_key": "s3cr3t"},
                context=_context({"dev-1": _device("dev-1", name="router1", source="ise")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "failure")
        self.assertIn("lab-ise", outcomes[0].summary)


if __name__ == "__main__":
    unittest.main()
