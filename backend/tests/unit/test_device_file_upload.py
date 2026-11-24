"""Tests for the helpers shared by upload-config and upload-binary."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from models.workflow_context import DeviceContext, WorkflowContext
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from services.network.netmiko.connection import FileTransferResult
from workflow_steps.common.device_file_upload import (
    RemoteTarget,
    delete_remote_file,
    parse_socket_timeout,
    record_transfer,
    remote_file_exists,
    upload_outcomes,
    verify_remote_digest,
)
from workflow_steps.common.device_runner import Batch


def _device(device_id: str = "d1") -> DeviceContext:
    return DeviceContext(id=device_id, name=device_id, hostname=device_id, primary_ip4="10.0.0.1")


class ParseSocketTimeoutTests(unittest.TestCase):
    def test_default_and_bounds(self) -> None:
        self.assertEqual(parse_socket_timeout({}, step_id="s"), 10)
        self.assertEqual(parse_socket_timeout({"socket_timeout": "30"}, step_id="s"), 30)
        for bad in (4, 301, "x"):
            with self.assertRaises(ValueError):
                parse_socket_timeout({"socket_timeout": bad}, step_id="s")


class RecordTransferTests(unittest.TestCase):
    def test_record_transfer_success_returns_no_failure(self) -> None:
        results, failed = record_transfer(
            device=_device(),
            node_id="n",
            command="cmd",
            result=FileTransferResult(success=True, file_transferred=True, file_verified=True),
            ok_summary="done",
            default_error="boom",
        )
        self.assertIsNone(failed)
        self.assertEqual(results["n"][0].summary, "done")
        self.assertTrue(results["n"][0].success)

    def test_record_transfer_failure_keeps_the_record_on_the_failed_device(self) -> None:
        device = _device()
        _, failed = record_transfer(
            device=device,
            node_id="n",
            command="cmd",
            result=FileTransferResult(success=False, error="SCP disabled"),
            ok_summary="done",
            default_error="boom",
        )
        assert failed is not None
        self.assertEqual((failed.code, failed.message), ("upload_failed", "SCP disabled"))
        # the record rides on the device the runner marks failed; the original is untouched
        assert failed.device is not None
        self.assertEqual(failed.device.command_results["n"][0].summary, "SCP disabled")
        self.assertEqual(device.command_results, {})


class UploadOutcomesTests(unittest.TestCase):
    def test_summaries_and_handles(self) -> None:
        context = WorkflowContext(
            run_id="r", workflow_id="w", devices={"a": _device("a"), "b": _device("b")}
        )
        batch = Batch(ok={"a": context.devices["a"]}, failed={"b": context.devices["b"]})

        outcomes = upload_outcomes(context, batch, noun="binary")

        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(outcomes[0].summary, "uploaded binary to 1 device(s)")
        self.assertEqual(outcomes[1].summary, "1 device(s) failed")

    def test_no_failure_outcome_when_nothing_failed(self) -> None:
        context = WorkflowContext(run_id="r", workflow_id="w", devices={})

        outcomes = upload_outcomes(context, Batch(), noun="config")

        self.assertEqual([o.name for o in outcomes], ["success"])


def _target(send_commands: AsyncMock) -> RemoteTarget:
    netmiko = MagicMock()
    netmiko.send_commands = send_commands
    return RemoteTarget(
        netmiko=netmiko,
        host="10.0.0.1",
        device=_device(),
        username="admin",
        password="secret",
        device_type="cisco_ios",
        credential_reference="lab",
    )


def _answer(output: str, *, success: bool = True, error: str | None = None):
    return NetmikoCommandResult(success=success, output=output, error=error)


class RemoteHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_forwards_the_read_timeout_only_when_given(self) -> None:
        send = AsyncMock(return_value=_answer("ok"))
        target = _target(send)
        await target.run("dir flash:x", read_timeout=120)
        self.assertEqual(send.call_args.kwargs["read_timeout"], 120)
        self.assertEqual(send.call_args.kwargs["commands"], ["dir flash:x"])
        await target.run("dir flash:x")
        self.assertIsNone(send.call_args.kwargs["read_timeout"])

    async def _verify(self, answer, *, local: str = "ab" * 16):
        return await verify_remote_digest(
            _target(AsyncMock(return_value=answer)),
            node_id="n",
            file_system="flash:",
            filename="x.bin",
            algorithm="md5",
            local_digest=local,
            read_timeout=600,
        )

    async def test_verify_matches_case_insensitively(self) -> None:
        check = await self._verify(_answer(f".Done!\nverify /md5 (flash:x.bin) = {'AB' * 16}"))
        self.assertTrue(check.ok)
        self.assertEqual(check.device_digest, "ab" * 16)
        self.assertTrue(check.command_result.success)
        self.assertEqual(check.command_result.command, "verify /md5 flash:x.bin")

    async def test_verify_mismatch_keeps_the_device_digest(self) -> None:
        check = await self._verify(_answer(f"verify /md5 (flash:x.bin) = {'cd' * 16}"))
        self.assertFalse(check.ok)
        self.assertEqual(check.device_digest, "cd" * 16)
        self.assertIn("mismatch", check.message or "")
        self.assertFalse(check.command_result.success)

    async def test_unreadable_answers_have_no_device_digest(self) -> None:
        for answer in (
            _answer("%Error verifying flash:x.bin"),
            _answer("", success=False, error="Pattern not detected"),
        ):
            check = await self._verify(answer)
            self.assertFalse(check.ok)
            self.assertIsNone(check.device_digest)
            self.assertFalse(check.command_result.success)

    async def test_file_exists_reads_the_dir_output(self) -> None:
        async def _exists(output: str, **kw):
            return await remote_file_exists(
                _target(AsyncMock(return_value=_answer(output, **kw))),
                file_system="flash:",
                filename="x.bin",
            )

        self.assertEqual((await _exists("Directory of flash:/x.bin"))[0], True)
        for missing in (
            "%Error opening flash:/x.bin (No such file or directory)",
            "Path does not exist",
        ):
            self.assertEqual((await _exists(missing))[0], False)
        unclear = await _exists("???")
        self.assertIsNone(unclear[0])
        self.assertIn("Unexpected", unclear[1] or "")
        failed = await _exists("", success=False, error="timed out")
        self.assertEqual((failed[0], failed[1]), (None, "timed out"))

    async def test_delete_is_best_effort(self) -> None:
        target = _target(AsyncMock(return_value=_answer("")))
        self.assertTrue(await delete_remote_file(target, file_system="flash:", filename="x"))
        self.assertEqual(
            target.netmiko.send_commands.call_args.kwargs["commands"], ["delete /force flash:x"]
        )
        failing = _target(AsyncMock(side_effect=RuntimeError("gone")))
        self.assertFalse(await delete_remote_file(failing, file_system="flash:", filename="x"))
        refused = _target(AsyncMock(return_value=_answer("", success=False, error="no")))
        self.assertFalse(await delete_remote_file(refused, file_system="flash:", filename="x"))
