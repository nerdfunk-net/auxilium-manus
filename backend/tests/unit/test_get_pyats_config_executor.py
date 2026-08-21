"""Tests for get-pyats-config executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.get_pyats_config.executor import execute

_CONFIG_SERVICE_TARGET = "workflow_steps.common.pyats_batch.PyATSSourceConfigService"
_SERVICE_FACTORY_TARGET = "workflow_steps.get_pyats_config.executor.service_factory"


def _device_with_testbed(
    device_id: str = "device-1", *, source_id: str = "lab-pyats"
) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name="router1",
        hostname="router1",
        status=DeviceStatus.OK,
        attribute_bags={
            "pyats_testbed": {
                "pyats_source_id": source_id,
                "host": "10.0.0.1",
                "os": "ios",
                "username": "admin",
                "password": seal_secret("secret"),
            }
        },
    )


_PARSED_HOSTNAME = {"raw": None, "parsed": {"hostname": "r1"}, "error": None}


def _shim_success_response(device_ids: list[str]) -> dict:
    return {
        "results": {
            device_id: {
                "success": True,
                "error": None,
                "commands": {
                    "show running-config": _PARSED_HOSTNAME,
                },
            }
            for device_id in device_ids
        }
    }


class GetPyatsConfigExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_parsed_config_on_success(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_credentials.return_value = MagicMock()
            shim = MagicMock()
            shim.run_job = AsyncMock(return_value=_shim_success_response(["device-1"]))
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config={"output_key": "pyats_config"},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_testbed()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        device = outcomes[0].context.devices["device-1"]
        self.assertIn(Capability.PARSED, device.capabilities)
        entry = device.parsed["pyats_config"]
        self.assertEqual(entry["running"], {"hostname": "r1"})
        self.assertNotIn("startup", entry)

        shim.run_job.assert_awaited_once()
        call_kwargs = shim.run_job.call_args.kwargs
        self.assertEqual(call_kwargs["operation"], "parse")
        self.assertEqual(call_kwargs["devices"][0]["password"], "secret")

    async def test_missing_testbed_bag_fails_device(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        device = DeviceContext(id="device-1", name="r1", hostname="r1", status=DeviceStatus.OK)
        with (
            patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db),
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            shim = MagicMock()
            shim.run_job = AsyncMock()
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config={},
                context=WorkflowContext(
                    run_id="run-uuid-1", workflow_id="wf-1", devices={"device-1": device}
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        names = [o.name for o in outcomes]
        self.assertIn("failure", names)
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices["device-1"].errors[0].code
        self.assertEqual(error_code, "missing_testbed")
        shim.run_job.assert_not_awaited()

    async def test_source_resolution_error_fails_device(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_credentials.side_effect = PyATSValidationError(
                "no credential"
            )
            shim = MagicMock()
            shim.run_job = AsyncMock()
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config={},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_testbed()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices["device-1"].errors[0].code
        self.assertEqual(error_code, "source_error")
        shim.run_job.assert_not_awaited()

    async def test_per_command_error_fails_device(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        response = {
            "results": {
                "device-1": {
                    "success": True,
                    "error": None,
                    "commands": {
                        "show running-config": {
                            "raw": None,
                            "parsed": None,
                            "error": "no parser",
                        },
                    },
                }
            }
        }
        with (
            patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_credentials.return_value = MagicMock()
            shim = MagicMock()
            shim.run_job = AsyncMock(return_value=response)
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config={},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_testbed()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices["device-1"].errors[0].code
        self.assertEqual(error_code, "parse_failed")

    async def test_no_devices_short_circuits(self) -> None:
        run = MagicMock()
        outcomes = await execute(
            config={},
            context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].context.devices, {})

    async def test_same_source_devices_are_batched_into_one_call(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        devices = {
            "device-1": _device_with_testbed("device-1"),
            "device-2": _device_with_testbed("device-2"),
        }
        with (
            patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_credentials.return_value = MagicMock()
            shim = MagicMock()
            shim.run_job = AsyncMock(
                return_value=_shim_success_response(["device-1", "device-2"])
            )
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config={},
                context=WorkflowContext(
                    run_id="run-uuid-1", workflow_id="wf-1", devices=devices
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        shim.run_job.assert_awaited_once()
        call_kwargs = shim.run_job.call_args.kwargs
        self.assertEqual(
            {d["name"] for d in call_kwargs["devices"]}, {"device-1", "device-2"}
        )
        success_outcome = next(o for o in outcomes if o.name == "success")
        self.assertEqual(set(success_outcome.context.devices), {"device-1", "device-2"})

    async def test_multi_source_devices_get_separate_calls(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        devices = {
            "device-1": _device_with_testbed("device-1", source_id="lab-a"),
            "device-2": _device_with_testbed("device-2", source_id="lab-b"),
        }
        with (
            patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_credentials.return_value = MagicMock()
            shim = MagicMock()

            async def fake_run_job(_credentials, *, operation, devices, commands, timeout_seconds):
                return _shim_success_response([d["name"] for d in devices])

            shim.run_job = AsyncMock(side_effect=fake_run_job)
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config={},
                context=WorkflowContext(
                    run_id="run-uuid-1", workflow_id="wf-1", devices=devices
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(shim.run_job.await_count, 2)
        success_outcome = next(o for o in outcomes if o.name == "success")
        self.assertEqual(set(success_outcome.context.devices), {"device-1", "device-2"})

    async def test_chunk_boundary_splits_into_multiple_calls(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        devices = {
            f"device-{i}": _device_with_testbed(f"device-{i}") for i in range(6)
        }
        with (
            patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_credentials.return_value = MagicMock()
            shim = MagicMock()

            async def fake_run_job(_credentials, *, operation, devices, commands, timeout_seconds):
                return _shim_success_response([d["name"] for d in devices])

            shim.run_job = AsyncMock(side_effect=fake_run_job)
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config={},
                context=WorkflowContext(
                    run_id="run-uuid-1", workflow_id="wf-1", devices=devices
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(shim.run_job.await_count, 2)
        success_outcome = next(o for o in outcomes if o.name == "success")
        self.assertEqual(len(success_outcome.context.devices), 6)

    async def test_whole_chunk_failure_fails_every_device_in_it(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        devices = {
            "device-1": _device_with_testbed("device-1"),
            "device-2": _device_with_testbed("device-2"),
        }
        with (
            patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
            patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_credentials.return_value = MagicMock()
            shim = MagicMock()
            shim.run_job = AsyncMock(side_effect=PyATSAPIError("timed out"))
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config={},
                context=WorkflowContext(
                    run_id="run-uuid-1", workflow_id="wf-1", devices=devices
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        self.assertEqual(set(failure_outcome.context.devices), {"device-1", "device-2"})
        for device in failure_outcome.context.devices.values():
            self.assertEqual(device.errors[0].code, "device_error")


if __name__ == "__main__":
    unittest.main()
