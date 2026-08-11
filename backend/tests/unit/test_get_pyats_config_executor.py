"""Tests for get-pyats-config executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.pyats.common.exceptions import PyATSValidationError
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.get_pyats_config.executor import execute


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


def _shim_success_response(device_id: str) -> dict:
    return {
        "results": {
            device_id: {
                "success": True,
                "error": None,
                "commands": {
                    "show running-config": _PARSED_HOSTNAME,
                    "show startup-config": _PARSED_HOSTNAME,
                },
            }
        }
    }


class GetPyatsConfigExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_parsed_config_on_success(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db),
            patch(
                "workflow_steps.get_pyats_config.executor.PyATSSourceConfigService"
            ) as config_service_cls,
            patch(
                "workflow_steps.get_pyats_config.executor.service_factory"
            ) as service_factory_mock,
        ):
            config_service_cls.return_value.resolve_credentials.return_value = MagicMock()
            shim = MagicMock()
            shim.run_job = AsyncMock(return_value=_shim_success_response("device-1"))
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
        self.assertEqual(entry["startup"], {"hostname": "r1"})

        shim.run_job.assert_awaited_once()
        call_kwargs = shim.run_job.call_args.kwargs
        self.assertEqual(call_kwargs["operation"], "parse")
        self.assertEqual(call_kwargs["devices"][0]["password"], "secret")

    async def test_missing_testbed_bag_fails_device(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        device = DeviceContext(id="device-1", name="r1", hostname="r1", status=DeviceStatus.OK)
        with patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db):
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

    async def test_source_resolution_error_fails_device(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db),
            patch(
                "workflow_steps.get_pyats_config.executor.PyATSSourceConfigService"
            ) as config_service_cls,
        ):
            config_service_cls.return_value.resolve_credentials.side_effect = PyATSValidationError(
                "no credential"
            )

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
                        "show startup-config": _PARSED_HOSTNAME,
                    },
                }
            }
        }
        with (
            patch("workflow_steps.get_pyats_config.executor.object_session", return_value=db),
            patch(
                "workflow_steps.get_pyats_config.executor.PyATSSourceConfigService"
            ) as config_service_cls,
            patch(
                "workflow_steps.get_pyats_config.executor.service_factory"
            ) as service_factory_mock,
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


if __name__ == "__main__":
    unittest.main()
