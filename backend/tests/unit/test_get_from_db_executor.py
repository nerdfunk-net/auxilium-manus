"""Tests for get-from-db executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.device_data_records import DeviceDataRecord
from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.device_data.device_data_service import DeviceDataService
from workflow_steps.get_from_db.executor import execute
from workflow_steps.store_in_db.executor import execute as store_execute


def _device(device_id: str = "device-1", name: str = "lab", **overrides: object) -> DeviceContext:
    defaults: dict[str, object] = {
        "id": device_id,
        "name": name,
        "hostname": name,
        "attribute_bags": {"nautobot": {"role": {"name": "router"}}},
    }
    defaults.update(overrides)
    return DeviceContext(**defaults)


class GetFromDbExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=[DeviceDataRecord.__table__])
        self.addCleanup(self.engine.dispose)
        self.Session = sessionmaker(bind=self.engine)
        for target in (
            "workflow_steps.get_from_db.executor.get_db_session",
            "workflow_steps.store_in_db.executor.get_db_session",
        ):
            patcher = patch(target, side_effect=lambda: self.Session())
            patcher.start()
            self.addCleanup(patcher.stop)

    def _seed(self, device_name: str, storage_key: str, data: object) -> None:
        with self.Session() as db:
            DeviceDataService(db).store_device_data(
                device_name=device_name, storage_key=storage_key, data=data
            )

    async def _run(self, *, config: dict, devices: dict[str, DeviceContext]):
        run = MagicMock()
        run.id = 1
        return await execute(
            config=config,
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="get-from-db-1",
            device_sessions=MagicMock(),
        )

    async def test_scalar_written_to_destination_path(self) -> None:
        self._seed("lab", "role", "router")
        outcomes = await self._run(
            config={"storage_key": "role", "destination_path": "stored.role"},
            devices={"device-1": _device()},
        )
        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["device-1"]
        self.assertEqual(device.attribute_bags["stored"]["role"], "router")
        self.assertEqual(device.status, DeviceStatus.OK)

    async def test_nested_dict_written_and_existing_bags_kept(self) -> None:
        self._seed("lab", "backup", {"a": {"b": 1}})
        outcomes = await self._run(
            config={"storage_key": "backup", "destination_path": "stored.backup"},
            devices={"device-1": _device()},
        )
        device = outcomes[0].context.devices["device-1"]
        self.assertEqual(device.attribute_bags["stored"]["backup"], {"a": {"b": 1}})
        self.assertEqual(device.attribute_bags["nautobot"], {"role": {"name": "router"}})

    async def test_missing_record_routes_device_to_failure(self) -> None:
        outcomes = await self._run(
            config={"storage_key": "nope", "destination_path": "stored.x"},
            devices={"device-1": _device()},
        )
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(outcomes[0].context.devices, {})
        failed = outcomes[1].context.devices["device-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "record_not_found")
        self.assertEqual(failed.errors[-1].step_id, "get-from-db")

    async def test_mixed_devices_split_between_outcomes(self) -> None:
        self._seed("lab", "role", "router")
        outcomes = await self._run(
            config={"storage_key": "role", "destination_path": "stored.role"},
            devices={"device-1": _device(), "device-2": _device("device-2", "other")},
        )
        self.assertEqual(list(outcomes[0].context.devices), ["device-1"])
        self.assertEqual(list(outcomes[1].context.devices), ["device-2"])

    async def test_null_stored_value_is_written(self) -> None:
        self._seed("lab", "nothing", None)
        outcomes = await self._run(
            config={"storage_key": "nothing", "destination_path": "stored.nothing"},
            devices={"device-1": _device()},
        )
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertIsNone(
            outcomes[0].context.devices["device-1"].attribute_bags["stored"]["nothing"]
        )

    async def test_blank_config_raises_value_error(self) -> None:
        for config in (
            {"storage_key": "", "destination_path": "stored.x"},
            {"storage_key": "k", "destination_path": " "},
            {"destination_path": "stored.x"},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                await self._run(config=config, devices={"device-1": _device()})

    async def test_reserved_destination_fails_device(self) -> None:
        self._seed("lab", "role", "router")
        outcomes = await self._run(
            config={"storage_key": "role", "destination_path": "parsed.role"},
            devices={"device-1": _device()},
        )
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["device-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)

    async def test_no_devices_returns_success_unchanged(self) -> None:
        outcomes = await self._run(
            config={"storage_key": "role", "destination_path": "stored.role"}, devices={}
        )
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(outcomes[0].context.devices, {})

    async def test_round_trip_with_store_in_db(self) -> None:
        device = _device()
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})
        run = MagicMock()
        run.id = 1
        await store_execute(
            config={
                "storage_key": "role",
                "content_source": "single_attribute",
                "attribute_path": "nautobot.role.name",
            },
            context=context,
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="store-in-db-1",
            device_sessions=MagicMock(),
        )
        outcomes = await self._run(
            config={"storage_key": "role", "destination_path": "restored.role"},
            devices={"device-1": _device(attribute_bags={})},
        )
        restored = outcomes[0].context.devices["device-1"]
        self.assertEqual(restored.attribute_bags["restored"]["role"], "router")


class DeviceDataServiceGetTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine, tables=[DeviceDataRecord.__table__])
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.service = DeviceDataService(self.db)

    def test_get_returns_record_or_none(self) -> None:
        self.service.store_device_data(device_name="lab", storage_key="k", data={"x": 1})
        record = self.service.get_device_data(device_name="lab", storage_key="k")
        self.assertIsNotNone(record)
        self.assertEqual(record.data, {"x": 1})
        self.assertIsNone(self.service.get_device_data(device_name="lab", storage_key="other"))
        self.assertIsNone(self.service.get_device_data(device_name="nope", storage_key="k"))


if __name__ == "__main__":
    unittest.main()
