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
from workflow_steps.configure_replace_config.executor import _diff_has_changes, execute

_NODE_ID = "configure-replace-config-1"
_DEVICE_ID = "device-1"
_REPLACE_COMMAND = "configure replace bootflash:new_config.txt force time 2"
_CONFIRM_COMMAND = "configure confirm"
_DIFF_COMMAND = "show archive config differences system:running-config bootflash:new_config.txt"
# IOS's real "no differences" response: a header line plus a "no changes"
# sentinel, never a truly blank body -- see _diff_has_changes.
_DIFF_NO_CHANGES = "!Contextual Config Diffs:\n!No changes were found"
# Diff checks default on; existing tests below focus on the replace/confirm
# flow itself, so they're pinned off here and exercised separately.
_BASE_CONFIG = {
    "destination_filename": "new_config.txt",
    "file_system": "bootflash:",
    "timeout_minutes": 2,
    "skip_if_no_pending_changes": False,
    "verify_diff_after_replace": False,
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


def _as_artifact_ref(payload: dict) -> ArtifactRef:
    return ArtifactRef.model_validate(payload)


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


def _replace_confirm_response(
    *,
    replace_raw: str | None = "Rollback Done",
    replace_error: str | None = None,
    include_confirm: bool = True,
    confirm_raw: str | None = None,
    confirm_error: str | None = None,
) -> dict:
    """Build the single-job response ``configure replace`` + ``configure confirm``
    now share (one connection, both commands -- see ``_run_shim_job``). The shim
    runs every command in the request regardless of an earlier command's error,
    so both entries are normally present even when replace failed.
    """
    commands = {_REPLACE_COMMAND: {"raw": replace_raw, "parsed": None, "error": replace_error}}
    if include_confirm:
        commands[_CONFIRM_COMMAND] = {
            "raw": confirm_raw,
            "parsed": None,
            "error": confirm_error,
        }
    return {
        "results": {
            _DEVICE_ID: {"success": True, "error": None, "commands": commands},
        }
    }


class DiffHasChangesTests(unittest.TestCase):
    def test_no_changes_sentinel_is_not_a_diff(self) -> None:
        self.assertFalse(_diff_has_changes(_DIFF_NO_CHANGES))

    def test_blank_output_is_not_a_diff(self) -> None:
        self.assertFalse(_diff_has_changes("   \n\n  "))

    def test_header_only_is_not_a_diff(self) -> None:
        self.assertFalse(_diff_has_changes("!Contextual Config Diffs:"))

    def test_real_diff_lines_are_a_diff(self) -> None:
        self.assertTrue(
            _diff_has_changes("!Contextual Config Diffs:\n+no ip http server\n-ip http server")
        )


class ConfigureReplaceConfigExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self,
        *,
        device: DeviceContext,
        run_job_side_effect,
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
                _replace_confirm_response(
                    replace_raw="Rollback Done",
                    confirm_raw="Confirm the configuration change",
                ),
            ],
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

        self.assertEqual(shim.run_job.await_count, 1)
        call = shim.run_job.call_args_list[0]
        self.assertEqual(call.kwargs["commands"], [_REPLACE_COMMAND, _CONFIRM_COMMAND])
        self.assertEqual(call.kwargs["devices"][0]["password"], "secret")

    async def test_missing_testbed_bag_fails_device(self) -> None:
        device = DeviceContext(id=_DEVICE_ID, name="r1", hostname="r1", status=DeviceStatus.OK)
        outcomes, shim, _ = await self._run(device=device, run_job_side_effect=[])

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices[_DEVICE_ID].errors[0].code
        self.assertEqual(error_code, "missing_testbed")
        shim.run_job.assert_not_awaited()

    async def test_job_connection_failure_fails_device(self) -> None:
        """The whole job/connection fails before any command runs (e.g. device
        unreachable) -- distinct from a per-command error on an otherwise-live
        session, which is covered by the archive/confirm-specific tests below."""
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[PyATSAPIError("connection timed out")],
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices[_DEVICE_ID].errors[0].code
        self.assertEqual(error_code, "replace_failed")
        self.assertEqual(shim.run_job.await_count, 1)

    async def test_replace_command_failure_fails_device(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[
                _replace_confirm_response(
                    replace_raw=None,
                    replace_error="Invalid config file bootflash:new_config.txt",
                    include_confirm=False,
                ),
            ],
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices[_DEVICE_ID].errors[0].code
        self.assertEqual(error_code, "replace_failed")
        self.assertEqual(shim.run_job.await_count, 1)

    async def test_replace_command_archive_not_configured_gives_clear_message(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[
                _replace_confirm_response(
                    replace_raw=None,
                    replace_error="%Turn config archive on before using Rollback Confirmed Change",
                    include_confirm=False,
                ),
            ],
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        err = failure_outcome.context.devices[_DEVICE_ID].errors[0]
        self.assertEqual(err.code, "archive_not_configured")
        self.assertIn("archive", err.message.lower())
        self.assertEqual(shim.run_job.await_count, 1)

    async def test_confirm_command_error_on_same_session_fails_device(self) -> None:
        """'configure replace' succeeds but the confirm command errors on that same,
        still-open connection (e.g. the channel drops between the two commands)."""
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[
                _replace_confirm_response(
                    replace_raw="Rollback Done",
                    confirm_error="connection reset by peer",
                ),
            ],
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        err = failure_outcome.context.devices[_DEVICE_ID].errors[0]
        self.assertEqual(err.code, "confirm_failed")
        self.assertIn("auto-revert", err.message)
        self.assertEqual(shim.run_job.await_count, 1)

    async def test_confirm_reports_no_pending_rollback_fails_device(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            run_job_side_effect=[
                _replace_confirm_response(
                    replace_raw="Rollback Done",
                    confirm_raw="%No Rollback Confirmed Change pending",
                ),
            ],
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        err = failure_outcome.context.devices[_DEVICE_ID].errors[0]
        self.assertEqual(err.code, "confirm_not_pending")
        self.assertEqual(shim.run_job.await_count, 1)

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

    async def test_skip_when_no_pending_changes(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            config={
                **_BASE_CONFIG,
                "skip_if_no_pending_changes": True,
            },
            run_job_side_effect=[
                _execute_response(_DIFF_COMMAND, raw="   \n"),
            ],
        )

        names = [o.name for o in outcomes]
        self.assertEqual(names, ["success"])
        device = outcomes[0].context.devices[_DEVICE_ID]
        entry = device.parsed[f"{_NODE_ID}.configure_replace"]
        self.assertTrue(entry["skipped"])
        self.assertEqual(entry["reason"], "no_pending_changes")
        self.assertEqual(shim.run_job.await_count, 1)
        self.assertEqual(shim.run_job.call_args_list[0].kwargs["commands"], [_DIFF_COMMAND])

    async def test_skip_when_diff_reports_no_changes_sentinel(self) -> None:
        """IOS's real 'no differences' response is a header + '!No changes were
        found' sentinel, never a blank body -- this must skip just like a
        truly empty diff, not be mistaken for a real diff."""
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            config={
                **_BASE_CONFIG,
                "skip_if_no_pending_changes": True,
            },
            run_job_side_effect=[
                _execute_response(_DIFF_COMMAND, raw=_DIFF_NO_CHANGES),
            ],
        )

        names = [o.name for o in outcomes]
        self.assertEqual(names, ["success"])
        device = outcomes[0].context.devices[_DEVICE_ID]
        entry = device.parsed[f"{_NODE_ID}.configure_replace"]
        self.assertTrue(entry["skipped"])
        self.assertEqual(shim.run_job.await_count, 1)

    async def test_pre_diff_nonempty_stores_artifact_and_proceeds(self) -> None:
        diff_text = "-no shutdown\n+shutdown"
        outcomes, shim, artifacts = await self._run(
            device=_device_with_testbed(),
            config={
                **_BASE_CONFIG,
                "skip_if_no_pending_changes": True,
            },
            run_job_side_effect=[
                _execute_response(_DIFF_COMMAND, raw=diff_text),
                _replace_confirm_response(
                    replace_raw="Rollback Done",
                    confirm_raw="Confirm the configuration change",
                ),
            ],
        )

        names = [o.name for o in outcomes]
        self.assertEqual(names, ["success"])
        device = outcomes[0].context.devices[_DEVICE_ID]
        diff_entry = device.parsed[f"{_NODE_ID}.configure_replace_diff"]
        artifact_ref = diff_entry["pre_diff_artifact_ref"]
        self.assertEqual(await artifacts.resolve(_as_artifact_ref(artifact_ref)), diff_text)
        self.assertEqual(shim.run_job.await_count, 2)

    async def test_pre_diff_command_error_proceeds_with_replace(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            config={
                **_BASE_CONFIG,
                "skip_if_no_pending_changes": True,
            },
            run_job_side_effect=[
                PyATSAPIError("diff command not supported"),
                _replace_confirm_response(
                    replace_raw="Rollback Done",
                    confirm_raw="Confirm the configuration change",
                ),
            ],
        )

        names = [o.name for o in outcomes]
        self.assertEqual(names, ["success"])
        self.assertEqual(shim.run_job.await_count, 2)

    async def test_post_diff_mismatch_fails_device(self) -> None:
        diff_text = "-no shutdown\n+shutdown"
        outcomes, shim, artifacts = await self._run(
            device=_device_with_testbed(),
            config={
                **_BASE_CONFIG,
                "verify_diff_after_replace": True,
            },
            run_job_side_effect=[
                _replace_confirm_response(
                    replace_raw="Rollback Done",
                    confirm_raw="Confirm the configuration change",
                ),
                _execute_response(_DIFF_COMMAND, raw=diff_text),
            ],
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        device = failure_outcome.context.devices[_DEVICE_ID]
        err = device.errors[0]
        self.assertEqual(err.code, "diff_mismatch")
        diff_entry = device.parsed[f"{_NODE_ID}.configure_replace_diff"]
        artifact_ref = diff_entry["post_diff_artifact_ref"]
        self.assertEqual(await artifacts.resolve(_as_artifact_ref(artifact_ref)), diff_text)
        self.assertEqual(shim.run_job.await_count, 2)

    async def test_post_diff_no_changes_sentinel_succeeds(self) -> None:
        """The post-check must recognize IOS's '!No changes were found'
        sentinel as 'matches', not fail the device with diff_mismatch."""
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            config={
                **_BASE_CONFIG,
                "verify_diff_after_replace": True,
            },
            run_job_side_effect=[
                _replace_confirm_response(
                    replace_raw="Rollback Done",
                    confirm_raw="Confirm the configuration change",
                ),
                _execute_response(_DIFF_COMMAND, raw=_DIFF_NO_CHANGES),
            ],
        )

        names = [o.name for o in outcomes]
        self.assertEqual(names, ["success"])
        device = outcomes[0].context.devices[_DEVICE_ID]
        self.assertTrue(device.parsed[f"{_NODE_ID}.configure_replace"]["confirmed"])
        self.assertEqual(shim.run_job.await_count, 2)

    async def test_post_diff_command_error_fails_device(self) -> None:
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            config={
                **_BASE_CONFIG,
                "verify_diff_after_replace": True,
            },
            run_job_side_effect=[
                _replace_confirm_response(
                    replace_raw="Rollback Done",
                    confirm_raw="Confirm the configuration change",
                ),
                PyATSAPIError("connection lost"),
            ],
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        err = failure_outcome.context.devices[_DEVICE_ID].errors[0]
        self.assertEqual(err.code, "post_verify_failed")
        self.assertEqual(shim.run_job.await_count, 2)

    async def test_default_flow_runs_both_diff_checks(self) -> None:
        diff_text = "-no shutdown\n+shutdown"
        outcomes, shim, _ = await self._run(
            device=_device_with_testbed(),
            config={
                "destination_filename": "new_config.txt",
                "file_system": "bootflash:",
                "timeout_minutes": 2,
            },
            run_job_side_effect=[
                _execute_response(_DIFF_COMMAND, raw=diff_text),
                _replace_confirm_response(
                    replace_raw="Rollback Done",
                    confirm_raw="Confirm the configuration change",
                ),
                _execute_response(_DIFF_COMMAND, raw="   "),
            ],
        )

        names = [o.name for o in outcomes]
        self.assertEqual(names, ["success"])
        device = outcomes[0].context.devices[_DEVICE_ID]
        self.assertTrue(device.parsed[f"{_NODE_ID}.configure_replace"]["confirmed"])
        self.assertIn(f"{_NODE_ID}.configure_replace_diff", device.parsed)
        self.assertEqual(shim.run_job.await_count, 3)

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
