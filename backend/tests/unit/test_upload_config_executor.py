"""Tests for upload-config executor."""

from __future__ import annotations

import hashlib
import os
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
from services.network.netmiko.connection import CommandResult, FileTransferResult
from workflow_steps.upload_config.executor import execute

UPDATED_CONTENT = "ntp server 192.168.178.10\n"


def _device_with_updated_content(device_id: str = "device-1") -> DeviceContext:
    artifact_ref = ArtifactRef(
        artifact_id="artifact-updated",
        kind="updated_content",
        size_bytes=len(UPDATED_CONTENT),
    )
    return DeviceContext(
        id=device_id,
        name="router1",
        hostname="router1",
        primary_ip4="10.0.0.1/24",
        network_driver="cisco_ios",
        parsed={
            "update-content-3.updated_content": {
                "artifact_ref": artifact_ref.model_dump(mode="json"),
                "step_node_id": "update-content-3",
                "output_key": "updated_content",
                "size_bytes": len(UPDATED_CONTENT),
                "kind": "updated_content",
                "match_counts": {},
            }
        },
        capabilities={Capability.IDENTITY, Capability.PARSED},
        status=DeviceStatus.OK,
    )


def _device_with_running_config(device_id: str = "device-1") -> DeviceContext:
    artifact_ref = ArtifactRef(
        artifact_id="artifact-running",
        kind="running_config",
        size_bytes=len(UPDATED_CONTENT),
    )
    return DeviceContext(
        id=device_id,
        name="router1",
        hostname="router1",
        primary_ip4="10.0.0.1/24",
        network_driver="cisco_ios",
        running_config_ref=artifact_ref,
        capabilities={Capability.IDENTITY, Capability.RUNNING_CONFIG},
        status=DeviceStatus.OK,
    )


def _base_config(**overrides: object) -> dict:
    config = {
        "credential_reference": "lab-ssh",
        "content_source": "updated_content",
        "source_step_node_id": "update-content-3",
        "destination_filename": "new-config.cfg",
        "file_system": "bootflash:",
    }
    config.update(overrides)
    return config


class UploadConfigExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_uploads_updated_content_by_default(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        captured_local_path: dict[str, str] = {}

        async def _fake_upload_file(**kwargs):
            captured_local_path["path"] = kwargs["local_path"]
            return FileTransferResult(success=True, file_transferred=True, file_verified=True)

        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.upload_config.executor.NetmikoService") as netmiko_cls,
            patch.object(artifact_service, "resolve", new=AsyncMock(return_value=UPDATED_CONTENT)),
        ):
            netmiko = netmiko_cls.return_value
            netmiko.upload_file = AsyncMock(side_effect=_fake_upload_file)

            outcomes = await execute(
                config=_base_config(),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        device = outcomes[0].context.devices["device-1"]
        results = device.command_results["upload-1"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].command, "upload-config")
        self.assertTrue(results[0].success)

        call_kwargs = netmiko.upload_file.call_args.kwargs
        self.assertEqual(call_kwargs["dest_file"], "new-config.cfg")
        self.assertEqual(call_kwargs["file_system"], "bootflash:")
        self.assertFalse(call_kwargs["overwrite"])
        self.assertFalse(call_kwargs["inline_transfer"])
        self.assertEqual(call_kwargs["socket_timeout"], 10)
        # temp file is written for the transfer, then cleaned up afterwards
        self.assertFalse(os.path.exists(captured_local_path["path"]))

    async def test_resolves_credential_scoped_to_triggering_user(self) -> None:
        run = MagicMock()
        run.id = 1
        run.triggered_by_id = 42
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ) as resolve_mock,
            patch("workflow_steps.upload_config.executor.NetmikoService") as netmiko_cls,
            patch.object(artifact_service, "resolve", new=AsyncMock(return_value=UPDATED_CONTENT)),
        ):
            netmiko = netmiko_cls.return_value
            netmiko.upload_file = AsyncMock(return_value=FileTransferResult(success=True))

            await execute(
                config=_base_config(),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        resolve_mock.assert_called_once_with(db, "lab-ssh", acting_user_id=42)

    async def test_running_config_source_does_not_require_source_step_node_id(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.upload_config.executor.NetmikoService") as netmiko_cls,
            patch.object(artifact_service, "resolve", new=AsyncMock(return_value=UPDATED_CONTENT)),
        ):
            netmiko = netmiko_cls.return_value
            netmiko.upload_file = AsyncMock(return_value=FileTransferResult(success=True))

            outcomes = await execute(
                config=_base_config(content_source="running_config", source_step_node_id=""),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_running_config()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "success")

    async def test_missing_source_step_node_id_raises_for_updated_content(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config=_base_config(source_step_node_id=""),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

    async def test_missing_destination_filename_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config=_base_config(destination_filename=""),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

    async def test_missing_file_system_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config=_base_config(file_system=""),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

    async def test_invalid_content_source_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config=_base_config(content_source="not_a_real_source"),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

    async def test_invalid_socket_timeout_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config=_base_config(socket_timeout=99999),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

    async def test_overwrite_and_inline_transfer_are_passed_through(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.upload_config.executor.NetmikoService") as netmiko_cls,
            patch.object(artifact_service, "resolve", new=AsyncMock(return_value=UPDATED_CONTENT)),
        ):
            netmiko = netmiko_cls.return_value
            netmiko.upload_file = AsyncMock(return_value=FileTransferResult(success=True))

            await execute(
                config=_base_config(overwrite=True, inline_transfer=True, socket_timeout=30),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        call_kwargs = netmiko.upload_file.call_args.kwargs
        self.assertTrue(call_kwargs["overwrite"])
        self.assertTrue(call_kwargs["inline_transfer"])
        self.assertEqual(call_kwargs["socket_timeout"], 30)

    async def test_transfer_failure_marks_device_failed(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.upload_config.executor.NetmikoService") as netmiko_cls,
            patch.object(artifact_service, "resolve", new=AsyncMock(return_value=UPDATED_CONTENT)),
        ):
            netmiko = netmiko_cls.return_value
            netmiko.upload_file = AsyncMock(
                return_value=FileTransferResult(success=False, error="SCP disabled on device")
            )

            outcomes = await execute(
                config=_base_config(),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        names = {outcome.name for outcome in outcomes}
        self.assertIn("failure", names)
        failed_device = next(o for o in outcomes if o.name == "failure").context.devices["device-1"]
        self.assertEqual(failed_device.errors[-1].code, "upload_failed")

    async def test_device_without_matching_content_fails(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
        ):
            device = DeviceContext(
                id="device-1",
                name="router1",
                hostname="router1",
                network_driver="cisco_ios",
                status=DeviceStatus.OK,
            )
            outcomes = await execute(
                config=_base_config(),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": device},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        names = {outcome.name for outcome in outcomes}
        self.assertIn("failure", names)
        failed_device = next(o for o in outcomes if o.name == "failure").context.devices["device-1"]
        self.assertEqual(failed_device.errors[-1].code, "updated_content_missing")

    async def test_verify_content_success_appends_verify_command_result(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        # UPDATED_CONTENT already ends with "\n"; Cisco IOS unconditionally appends
        # another one on top of whatever was sent (see _NEWLINE_APPENDED_DEVICE_TYPES),
        # so the device's real digest covers content + two trailing newlines.
        expected_digest = hashlib.md5(  # noqa: S324 -- test fixture, not security-sensitive
            (UPDATED_CONTENT + "\n").encode("utf-8")
        ).hexdigest()
        command = "verify /md5 bootflash:new-config.cfg"
        output = f".Done!\nverify /md5 (bootflash:new-config.cfg) = {expected_digest}\n"
        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.upload_config.executor.NetmikoService") as netmiko_cls,
            patch.object(artifact_service, "resolve", new=AsyncMock(return_value=UPDATED_CONTENT)),
        ):
            netmiko = netmiko_cls.return_value
            netmiko.upload_file = AsyncMock(
                return_value=FileTransferResult(
                    success=True, file_transferred=True, file_verified=True
                )
            )
            netmiko.send_commands = AsyncMock(
                return_value=CommandResult(
                    success=True, output=output, command_outputs={command: output}
                )
            )

            outcomes = await execute(
                config=_base_config(verify_content=True, verify_algorithm="md5"),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "success")
        device = outcomes[0].context.devices["device-1"]
        results = device.command_results["upload-1"]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1].command, command)
        self.assertTrue(results[1].success)
        self.assertIn(expected_digest, results[1].summary or "")

    async def test_verify_content_mismatch_routes_to_failure(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        command = "verify /sha512 bootflash:new-config.cfg"
        wrong_digest = "a" * 128
        output = f".Done!\nverify /sha512 (bootflash:new-config.cfg) = {wrong_digest}\n"
        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.upload_config.executor.NetmikoService") as netmiko_cls,
            patch.object(artifact_service, "resolve", new=AsyncMock(return_value=UPDATED_CONTENT)),
        ):
            netmiko = netmiko_cls.return_value
            netmiko.upload_file = AsyncMock(return_value=FileTransferResult(success=True))
            netmiko.send_commands = AsyncMock(
                return_value=CommandResult(
                    success=True, output=output, command_outputs={command: output}
                )
            )

            outcomes = await execute(
                config=_base_config(verify_content=True, verify_algorithm="sha512"),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        names = {outcome.name for outcome in outcomes}
        self.assertIn("failure", names)
        failed_device = next(o for o in outcomes if o.name == "failure").context.devices["device-1"]
        self.assertEqual(failed_device.errors[-1].code, "verify_failed")
        self.assertIn(wrong_digest, failed_device.errors[-1].message)

    async def test_verify_content_unparseable_output_routes_to_failure(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.upload_config.executor.NetmikoService") as netmiko_cls,
            patch.object(artifact_service, "resolve", new=AsyncMock(return_value=UPDATED_CONTENT)),
        ):
            netmiko = netmiko_cls.return_value
            netmiko.upload_file = AsyncMock(return_value=FileTransferResult(success=True))
            netmiko.send_commands = AsyncMock(
                return_value=CommandResult(
                    success=True, output="% Invalid input detected\n", command_outputs={}
                )
            )

            outcomes = await execute(
                config=_base_config(verify_content=True, verify_algorithm="md5"),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        names = {outcome.name for outcome in outcomes}
        self.assertIn("failure", names)
        failed_device = next(o for o in outcomes if o.name == "failure").context.devices["device-1"]
        self.assertEqual(failed_device.errors[-1].code, "verify_failed")
        self.assertIn("Could not parse", failed_device.errors[-1].message)

    async def test_invalid_verify_algorithm_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config=_base_config(verify_content=True, verify_algorithm="sha1"),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

    async def test_verify_content_appends_newline_for_cisco_ios(self) -> None:
        # Rendered-template content typically has no trailing newline at all (the
        # Jinja renderer strips it), and Cisco IOS/IOS-XE unconditionally append one
        # "\n" to whatever was sent. The comparison digest must account for that, or
        # every rendered-template upload would spuriously fail verification.
        no_trailing_newline_content = UPDATED_CONTENT.rstrip("\n")
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        # Digest of what the device actually stores (content + Cisco's auto newline).
        expected_digest = hashlib.md5(  # noqa: S324 -- test fixture, not security-sensitive
            (no_trailing_newline_content + "\n").encode("utf-8")
        ).hexdigest()
        command = "verify /md5 bootflash:new-config.cfg"
        output = f".Done!\nverify /md5 (bootflash:new-config.cfg) = {expected_digest}\n"
        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.upload_config.executor.NetmikoService") as netmiko_cls,
            patch.object(
                artifact_service, "resolve", new=AsyncMock(return_value=no_trailing_newline_content)
            ),
        ):
            netmiko = netmiko_cls.return_value
            netmiko.upload_file = AsyncMock(return_value=FileTransferResult(success=True))
            netmiko.send_commands = AsyncMock(
                return_value=CommandResult(
                    success=True, output=output, command_outputs={command: output}
                )
            )

            outcomes = await execute(
                config=_base_config(verify_content=True, verify_algorithm="md5"),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "success")

    async def test_verify_content_does_not_normalize_newline_for_non_cisco_ios(self) -> None:
        # A platform without the documented Cisco IOS trailing-newline quirk must be
        # compared byte-for-byte, with no implicit normalization.
        no_trailing_newline_content = UPDATED_CONTENT.rstrip("\n")
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        expected_digest = hashlib.md5(  # noqa: S324 -- test fixture, not security-sensitive
            no_trailing_newline_content.encode("utf-8")
        ).hexdigest()
        command = "verify /md5 bootflash:new-config.cfg"
        output = f".Done!\nverify /md5 (bootflash:new-config.cfg) = {expected_digest}\n"
        device = _device_with_updated_content().model_copy(update={"network_driver": "arista_eos"})
        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.upload_config.executor.NetmikoService") as netmiko_cls,
            patch.object(
                artifact_service, "resolve", new=AsyncMock(return_value=no_trailing_newline_content)
            ),
        ):
            netmiko = netmiko_cls.return_value
            netmiko.upload_file = AsyncMock(return_value=FileTransferResult(success=True))
            netmiko.send_commands = AsyncMock(
                return_value=CommandResult(
                    success=True, output=output, command_outputs={command: output}
                )
            )

            outcomes = await execute(
                config=_base_config(verify_content=True, verify_algorithm="md5"),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": device},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "success")

    async def test_verify_content_matches_device_reported_regression_case(self) -> None:
        # Literal regression case: rendered content that already ends with a single
        # "\n" (e.g. update-content output). Cisco IOS appends its own "\n" on top,
        # so the device's real file — and its real checksum — has a trailing blank
        # line. Naively normalizing to a single trailing newline (an earlier, wrong
        # fix) computed 69ee59dbfa3adb32cbf8cc0b2684a6bc here instead of the real
        # d90e3c038a1766c3225996e4170e9654, and every such upload spuriously failed.
        content = (
            "username testuser privilege 15 secret test\n"
            "username testuser2 privilege 15 secret test\n"
            "username noc privilege 15 secret noc\n"
        )
        self.assertEqual(hashlib.md5(content.encode("utf-8")).hexdigest(), "69ee59dbfa3adb32cbf8cc0b2684a6bc")  # noqa: E501, S324 -- known-value regression fixture, not security-sensitive
        device_reported_digest = "d90e3c038a1766c3225996e4170e9654"
        self.assertEqual(
            hashlib.md5((content + "\n").encode("utf-8")).hexdigest(),  # noqa: S324
            device_reported_digest,
        )

        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        command = "verify /md5 nvram:manus-config"
        output = f".Done!\nverify /md5 (nvram:manus-config) = {device_reported_digest}\n"
        with (
            patch(
                "workflow_steps.upload_config.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.upload_config.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.upload_config.executor.NetmikoService") as netmiko_cls,
            patch.object(artifact_service, "resolve", new=AsyncMock(return_value=content)),
        ):
            netmiko = netmiko_cls.return_value
            netmiko.upload_file = AsyncMock(return_value=FileTransferResult(success=True))
            netmiko.send_commands = AsyncMock(
                return_value=CommandResult(
                    success=True, output=output, command_outputs={command: output}
                )
            )

            outcomes = await execute(
                config=_base_config(
                    verify_content=True,
                    verify_algorithm="md5",
                    destination_filename="manus-config",
                    file_system="nvram:",
                ),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_updated_content()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="upload-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].name, "success")


if __name__ == "__main__":
    unittest.main()
