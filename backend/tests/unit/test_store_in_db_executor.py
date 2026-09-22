"""Tests for store-in-db executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.device_data_records import DeviceDataRecord
from models.workflow_context import ArtifactRef, DeviceContext, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.store_in_db.executor import execute


def _device(**overrides: object) -> DeviceContext:
    defaults: dict[str, object] = {
        "id": "device-1",
        "name": "lab",
        "hostname": "lab",
        "attribute_bags": {"nautobot": {"role": {"name": "router"}}},
    }
    defaults.update(overrides)
    return DeviceContext(**defaults)


class StoreInDbExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=[DeviceDataRecord.__table__])
        self.addCleanup(self.engine.dispose)
        self.Session = sessionmaker(bind=self.engine)
        self.get_db_patcher = patch(
            "workflow_steps.store_in_db.executor.get_db_session",
            side_effect=lambda: self.Session(),
        )
        self.get_db_patcher.start()
        self.addCleanup(self.get_db_patcher.stop)

    def _rows(self) -> list[DeviceDataRecord]:
        with self.Session() as db:
            return list(db.scalars(select(DeviceDataRecord)))

    async def _run(self, *, config: dict, device: DeviceContext, artifact_service=None):
        run = MagicMock()
        run.id = 1
        return await execute(
            config=config,
            context=WorkflowContext(
                run_id="run-1", workflow_id="wf-1", devices={"device-1": device}
            ),
            run=run,
            artifact_service=artifact_service or InMemoryArtifactService(),
            node_id="store-in-db-1",
            device_sessions=MagicMock(),
        )

    async def test_device_data_stores_bags_and_parsed(self) -> None:
        device = _device(parsed={"cisco_config": {"hostname": "lab"}})
        outcomes = await self._run(
            config={"storage_key": "backup", "content_source": "device_data"}, device=device
        )

        self.assertEqual([o.name for o in outcomes], ["success"])
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].device_name, "lab")
        self.assertEqual(rows[0].storage_key, "backup")
        self.assertEqual(
            rows[0].data,
            {
                "attribute_bags": {"nautobot": {"role": {"name": "router"}}},
                "parsed": {"cisco_config": {"hostname": "lab"}},
            },
        )

    async def test_attribute_bags_stores_bags_only(self) -> None:
        device = _device(parsed={"cisco_config": {"hostname": "lab"}})
        await self._run(
            config={"storage_key": "backup", "content_source": "attribute_bags"}, device=device
        )
        rows = self._rows()
        self.assertEqual(rows[0].data, {"nautobot": {"role": {"name": "router"}}})

    async def test_single_attribute_stores_resolved_value(self) -> None:
        device = _device()
        outcomes = await self._run(
            config={
                "storage_key": "role",
                "content_source": "single_attribute",
                "attribute_path": "nautobot.role.name",
            },
            device=device,
        )
        self.assertEqual([o.name for o in outcomes], ["success"])
        rows = self._rows()
        self.assertEqual(rows[0].data, "router")

    async def test_single_attribute_missing_path_fails_device(self) -> None:
        device = _device()
        outcomes = await self._run(
            config={"storage_key": "role", "content_source": "single_attribute"}, device=device
        )
        names = [o.name for o in outcomes]
        self.assertIn("failure", names)
        self.assertEqual(self._rows(), [])

    async def test_single_attribute_secret_value_fails_device(self) -> None:
        device = _device(
            attribute_bags={"tacacs": {"shared_secret": seal_secret("s3cr3t")}}
        )
        outcomes = await self._run(
            config={
                "storage_key": "secret",
                "content_source": "single_attribute",
                "attribute_path": "tacacs.shared_secret",
            },
            device=device,
        )
        failure = next(o for o in outcomes if o.name == "failure")
        error = failure.context.devices["device-1"].errors[-1]
        self.assertIn("secret-valued attribute", error.message)
        self.assertEqual(self._rows(), [])

    async def test_single_attribute_secret_value_stored_when_allowed(self) -> None:
        device = _device(
            attribute_bags={"tacacs": {"shared_secret": seal_secret("s3cr3t")}}
        )
        outcomes = await self._run(
            config={
                "storage_key": "secret",
                "content_source": "single_attribute",
                "attribute_path": "tacacs.shared_secret",
                "allow_secret_storage": True,
            },
            device=device,
        )
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(self._rows()[0].data, "s3cr3t")

    async def test_rendered_template_stores_resolved_content(self) -> None:
        artifact_ref = ArtifactRef(artifact_id="artifact-1", kind="rendered_template", size_bytes=5)
        device = _device(
            parsed={
                "device_config": {
                    "artifact_ref": artifact_ref.model_dump(mode="json"),
                    "step_node_id": "render-jinja-template-2",
                    "output_key": "device_config",
                    "kind": "rendered_template",
                }
            }
        )
        artifact_service = InMemoryArtifactService()
        with patch.object(artifact_service, "resolve", new=AsyncMock(return_value="hostname lab")):
            outcomes = await self._run(
                config={
                    "storage_key": "template",
                    "content_source": "rendered_template",
                    "source_step_node_id": "render-jinja-template-2",
                    "parsed_output_key": "device_config",
                },
                device=device,
                artifact_service=artifact_service,
            )
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(self._rows()[0].data, "hostname lab")

    async def test_rendered_template_missing_source_step_fails_device(self) -> None:
        device = _device()
        outcomes = await self._run(
            config={"storage_key": "template", "content_source": "rendered_template"},
            device=device,
        )
        self.assertIn("failure", [o.name for o in outcomes])
        self.assertEqual(self._rows(), [])

    async def test_rendered_template_without_output_key_stores_all_by_key(self) -> None:
        artifact_ref = ArtifactRef(artifact_id="artifact-1", kind="rendered_template", size_bytes=5)
        device = _device(
            parsed={
                "device_config": {
                    "artifact_ref": artifact_ref.model_dump(mode="json"),
                    "step_node_id": "render-jinja-template-2",
                    "output_key": "device_config",
                    "kind": "rendered_template",
                }
            }
        )
        artifact_service = InMemoryArtifactService()
        with patch.object(artifact_service, "resolve", new=AsyncMock(return_value="hostname lab")):
            outcomes = await self._run(
                config={
                    "storage_key": "template",
                    "content_source": "rendered_template",
                    "source_step_node_id": "render-jinja-template-2",
                },
                device=device,
                artifact_service=artifact_service,
            )
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(self._rows()[0].data, {"device_config": "hostname lab"})

    async def test_no_devices_returns_bare_success(self) -> None:
        run = MagicMock()
        run.id = 1
        outcomes = await execute(
            config={"storage_key": "x", "content_source": "device_data"},
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={}),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="store-in-db-1",
            device_sessions=MagicMock(),
        )
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(self._rows(), [])

    async def test_rendered_template_no_match_fails_device(self) -> None:
        device = _device()
        outcomes = await self._run(
            config={
                "storage_key": "template",
                "content_source": "rendered_template",
                "source_step_node_id": "render-jinja-template-2",
            },
            device=device,
        )
        self.assertIn("failure", [o.name for o in outcomes])
        self.assertEqual(self._rows(), [])

    async def test_missing_storage_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            await self._run(config={"content_source": "device_data"}, device=_device())

    async def test_invalid_content_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            await self._run(
                config={"storage_key": "x", "content_source": "not-a-real-source"},
                device=_device(),
            )

    async def test_second_run_overwrites_same_key(self) -> None:
        device = _device()
        await self._run(
            config={"storage_key": "role", "content_source": "attribute_bags"}, device=device
        )
        device2 = _device(attribute_bags={"nautobot": {"role": {"name": "switch"}}})
        await self._run(
            config={"storage_key": "role", "content_source": "attribute_bags"}, device=device2
        )
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data, {"nautobot": {"role": {"name": "switch"}}})


if __name__ == "__main__":
    unittest.main()
