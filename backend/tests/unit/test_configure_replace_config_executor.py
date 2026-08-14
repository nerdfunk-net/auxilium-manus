"""Tests for configure-replace-config executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    ArtifactRef,
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.configure_replace_config.executor import execute

_NODE_ID = "configure-replace-config-1"
_DEVICE_ID = "device-1"
_REPLACE_COMMAND = "configure replace bootflash:new_config.txt time 2 force"
_CONFIRM_COMMAND = "configure confirm"
_BASE_CONFIG = {
    "destination_filename": "new_config.txt",
    "file_system": "bootflash:",
    "timeout_minutes": 2,
}


def _device_with_testbed(*, source_id: str = "lab-pyats") -> DeviceContext:
    return DeviceContext(
        id=_DEVICE_ID,
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


def _learn_response(feature: str, data: dict | None, *, error: str | None = None) -> dict:
    return {
        "results": {
            _DEVICE_ID: {
                "success": True,
                "error": None,
                "commands": {feature: {"raw": None, "parsed": data, "error": error}},
            }
        }
    }


def _execute_response(command: str, *, raw: str = "", error: str | None = None) -> dict:
    return {
        "results": {
            _DEVICE_ID: {
                "success": True,
                "error": None,
                "commands": {command: {"raw": raw, "parsed": None, "error": error}},
            }
        }
    }


class ConfigureReplaceConfigExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self,
        *,
        device: DeviceContext,
        run_job_side_effect,
        diff_result: dict | None = None,
        diff_side_effect: Exception | None = None,
        config: dict | None = None,
        artifact_service: InMemoryArtifactService | None = None,
        resolve_credentials_side_effect: Exception | None = None,
    ):
        run = MagicMock()
        run.id = 42
        db = MagicMock()
        artifact_service = artifact_service or InMemoryArtifactService()

        with (
            patch(
                "workflow_steps.configure_replace_config.executor.object_session", return_value=db
            ),
            patch(
                "workflow_steps.configure_replace_config.executor.PyATSSourceConfigService"
            ) as config_service_cls,
            patch(
                "workflow_steps.configure_replace_config.executor.service_factory"
            ) as service_factory_mock,
        ):
            if resolve_credentials_side_effect is not None:
                config_service_cls.return_value.resolve_credentials.side_effect = (
                    resolve_credentials_side_effect
                )
            else:
                config_service_cls.return_value.resolve_credentials.return_value = MagicMock()

            shim = MagicMock()
            shim.run_job = AsyncMock(side_effect=run_job_side_effect)
            if diff_side_effect is not None:
                shim.diff = AsyncMock(side_effect=diff_side_effect)
            else:
                shim.diff = AsyncMock(return_value=diff_result or {"identical": True, "diff": ""})
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config=config or _BASE_CONFIG,
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={_DEVICE_ID: device},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id=_NODE_ID,
                device_sessions=MagicMock(),
            )
        return outcomes, shim, artifact_service

    async def test_happy_path_confirms_change(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[
                _learn_response("interface", {"Gi0/0": {"status": "up"}}),
                _execute_response(_REPLACE_COMMAND),
                _learn_response("interface", {"Gi0/0": {"status": "up"}}),
                _execute_response(_CONFIRM_COMMAND),
            ],
            diff_result={"identical": True, "diff": ""},
        )

        names = [o.name for o in outcomes]
        self.assertEqual(names, ["success"])
        device = outcomes[0].context.devices[_DEVICE_ID]
        self.assertEqual(device.status, DeviceStatus.OK)
        self.assertIn(Capability.PARSED, device.capabilities)
        entry = device.parsed[f"{_NODE_ID}.configure_replace"]
        self.assertTrue(entry["confirmed"])
        self.assertEqual(entry["destination_filename"], "new_config.txt")
        self.assertEqual(entry["file_system"], "bootflash:")
        self.assertEqual(entry["timeout_minutes"], 2)

        self.assertEqual(shim.run_job.await_count, 4)
        replace_call = shim.run_job.call_args_list[1]
        self.assertEqual(replace_call.kwargs["commands"], [_REPLACE_COMMAND])
        self.assertEqual(replace_call.kwargs["devices"][0]["password"], "secret")
        confirm_call = shim.run_job.call_args_list[3]
        self.assertEqual(confirm_call.kwargs["commands"], [_CONFIRM_COMMAND])

        diff_call_kwargs = shim.diff.call_args.kwargs
        self.assertEqual(diff_call_kwargs["snapshot_a"], {"Gi0/0": {"status": "up"}})
        self.assertEqual(diff_call_kwargs["snapshot_b"], {"Gi0/0": {"status": "up"}})

    async def test_missing_testbed_bag_fails_device(self) -> None:
        device = DeviceContext(id=_DEVICE_ID, name="r1", hostname="r1", status=DeviceStatus.OK)
        outcomes, shim, _ = await self._run(device=device, run_job_side_effect=[])

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices[_DEVICE_ID].errors[0].code
        self.assertEqual(error_code, "missing_testbed")
        shim.run_job.assert_not_awaited()

    async def test_pre_snapshot_failure_stops_before_replace(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[
                _learn_response("interface", None, error="connection refused"),
            ],
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices[_DEVICE_ID].errors[0].code
        self.assertEqual(error_code, "pre_snapshot_failed")
        self.assertEqual(shim.run_job.await_count, 1)
        shim.diff.assert_not_awaited()

    async def test_replace_command_failure_stops_before_post_snapshot(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[
                _learn_response("interface", {"Gi0/0": {"status": "up"}}),
                _execute_response(
                    _REPLACE_COMMAND, error="Invalid config file bootflash:new_config.txt"
                ),
            ],
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices[_DEVICE_ID].errors[0].code
        self.assertEqual(error_code, "replace_failed")
        self.assertEqual(shim.run_job.await_count, 2)
        shim.diff.assert_not_awaited()

    async def test_post_snapshot_connection_lost_skips_confirm(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[
                _learn_response("interface", {"Gi0/0": {"status": "up"}}),
                _execute_response(_REPLACE_COMMAND),
                PyATSAPIError("connection timed out"),
            ],
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        err = failure_outcome.context.devices[_DEVICE_ID].errors[0]
        self.assertEqual(err.code, "post_snapshot_failed")
        self.assertIn("auto-revert", err.message)
        self.assertEqual(shim.run_job.await_count, 3)
        shim.diff.assert_not_awaited()

    async def test_diff_mismatch_skips_confirm_and_stores_diff(self) -> None:
        artifact_service = InMemoryArtifactService()
        outcomes, shim, artifact_service = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[
                _learn_response("interface", {"Gi0/0": {"status": "up"}}),
                _execute_response(_REPLACE_COMMAND),
                _learn_response("interface", {"Gi0/0": {"status": "down"}}),
            ],
            diff_result={"identical": False, "diff": "-status: up\n+status: down\n"},
            artifact_service=artifact_service,
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        device = failure_outcome.context.devices[_DEVICE_ID]
        self.assertEqual(device.errors[0].code, "verification_failed")
        entry = device.parsed[f"{_NODE_ID}.configure_replace"]
        self.assertFalse(entry["confirmed"])
        diff_text = await artifact_service.resolve(
            ArtifactRef.model_validate(entry["diff_artifact_ref"])
        )
        self.assertIn("status", diff_text)
        # Only pre/replace/post learn+execute calls -- no confirm.
        self.assertEqual(shim.run_job.await_count, 3)

    async def test_diff_shim_error_skips_confirm(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[
                _learn_response("interface", {"Gi0/0": {"status": "up"}}),
                _execute_response(_REPLACE_COMMAND),
                _learn_response("interface", {"Gi0/0": {"status": "up"}}),
            ],
            diff_side_effect=PyATSValidationError("bad snapshot shape"),
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices[_DEVICE_ID].errors[0].code
        self.assertEqual(error_code, "diff_failed")
        self.assertEqual(shim.run_job.await_count, 3)

    async def test_confirm_failure_fails_device_after_clean_verification(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[
                _learn_response("interface", {"Gi0/0": {"status": "up"}}),
                _execute_response(_REPLACE_COMMAND),
                _learn_response("interface", {"Gi0/0": {"status": "up"}}),
                _execute_response(_CONFIRM_COMMAND, error="% Nothing to confirm"),
            ],
            diff_result={"identical": True, "diff": ""},
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        err = failure_outcome.context.devices[_DEVICE_ID].errors[0]
        self.assertEqual(err.code, "confirm_failed")
        self.assertIn("auto-revert", err.message)
        self.assertEqual(shim.run_job.await_count, 4)

    async def test_source_resolution_error_fails_device(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[],
            resolve_credentials_side_effect=PyATSValidationError("no credential"),
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices[_DEVICE_ID].errors[0].code
        self.assertEqual(error_code, "source_error")
        shim.run_job.assert_not_awaited()

    async def test_missing_destination_filename_raises_value_error(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={**_BASE_CONFIG, "destination_filename": ""},
                context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id=_NODE_ID,
                device_sessions=MagicMock(),
            )

    async def test_missing_file_system_raises_value_error(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={**_BASE_CONFIG, "file_system": ""},
                context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id=_NODE_ID,
                device_sessions=MagicMock(),
            )

    async def test_timeout_minutes_out_of_range_raises_value_error(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={**_BASE_CONFIG, "timeout_minutes": 0},
                context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id=_NODE_ID,
                device_sessions=MagicMock(),
            )
        with self.assertRaises(ValueError):
            await execute(
                config={**_BASE_CONFIG, "timeout_minutes": 121},
                context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id=_NODE_ID,
                device_sessions=MagicMock(),
            )

    async def test_non_integer_timeout_minutes_raises_value_error(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={**_BASE_CONFIG, "timeout_minutes": "two"},
                context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id=_NODE_ID,
                device_sessions=MagicMock(),
            )

    async def test_no_devices_short_circuits(self) -> None:
        run = MagicMock()
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id=_NODE_ID,
            device_sessions=MagicMock(),
        )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].context.devices, {})


if __name__ == "__main__":
    unittest.main()
