"""get-from-user resolves an inventory-reference run input to the inventory's devices."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.sources_nautobot import DeviceInfo
from models.workflow_context import WorkflowContext
from workflow_steps.get_from_user import executor, inventory_reference

_MOD = "workflow_steps.get_from_user.inventory_reference"


class InventoryReferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_inventory_id_becomes_the_inventory_devices(self) -> None:
        run = MagicMock(id=1, run_inputs={"target_devices": 1}, triggered_by_id=5)
        service = MagicMock()
        service.resolve_saved_inventory_devices_by_id = AsyncMock(
            return_value=[
                DeviceInfo(id="a", name="r1", primary_ip4="10.0.0.1/24"),
                DeviceInfo(id="b", name="r2", primary_ip4="10.0.0.2"),
            ]
        )
        db = MagicMock()
        user = MagicMock()
        user.username = "alice"
        with (
            patch.object(executor, "object_session", return_value=db),
            patch.object(executor, "is_inventory_reference", return_value=True),
            patch.object(inventory_reference, "object_session", return_value=db),
            patch(f"{_MOD}.UserRepository") as users,
            patch(f"{_MOD}._pick_source_id", return_value="src"),
            patch(f"{_MOD}.resolve_nautobot_credentials"),
            patch(f"{_MOD}.service_factory.build_nautobot_source_service", return_value=service),
        ):
            users.return_value.get_by_id.return_value = user
            outcomes = await executor.execute(
                config={"device_param": "target_devices"},
                context=WorkflowContext(run_id="1", workflow_id="1"),
                run=run,
                artifact_service=MagicMock(),
                node_id="n1",
                device_sessions=MagicMock(),
            )
        service.resolve_saved_inventory_devices_by_id.assert_awaited_once_with(1, "alice")
        names = sorted(d.name for d in outcomes[0].context.devices.values())
        self.assertEqual(names, ["r1", "r2"])

    def test_detects_only_inventory_reference_attributes(self) -> None:
        db = MagicMock()
        run = MagicMock(workflow_id=3)
        attrs = [{"name": "t", "type": "reference", "ref_kind": "inventory"}]
        db.get.return_value = MagicMock(static_attributes=attrs)
        self.assertTrue(inventory_reference.is_inventory_reference(db, run, "t"))
        self.assertFalse(inventory_reference.is_inventory_reference(db, run, "other"))
        attrs[0]["ref_kind"] = "credential"
        self.assertFalse(inventory_reference.is_inventory_reference(db, run, "t"))


class NoDatabaseSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_run_without_a_session_is_a_runtime_error(self) -> None:
        run = MagicMock(id=1, triggered_by_id=None)
        with patch(f"{_MOD}.object_session", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "no active DB session"):
                await inventory_reference.inventory_device_text(run, {}, 1)

    async def test_the_step_without_a_session_does_not_read_the_id_as_a_device_name(self) -> None:
        """W10-04: run input "1" used to become the device name "1"."""
        run = MagicMock(id=1, run_inputs={"target_devices": "1"}, triggered_by_id=5)
        with patch.object(executor, "object_session", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "no active DB session"):
                await executor.execute(
                    config={"device_param": "target_devices"},
                    context=WorkflowContext(run_id="1", workflow_id="1"),
                    run=run,
                    artifact_service=MagicMock(),
                    node_id="n1",
                    device_sessions=MagicMock(),
                )

    async def test_a_non_numeric_reference_is_a_value_error(self) -> None:
        with patch(f"{_MOD}.object_session", return_value=MagicMock()):
            with self.assertRaisesRegex(ValueError, "did not resolve to an inventory id"):
                await inventory_reference.inventory_device_text(MagicMock(), {}, "abc")
