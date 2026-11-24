"""Tests for the upload-binary executor."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult, FileTransferResult
from workflow_steps.upload_binary.executor import execute

IMAGE = b"\x00\xff\xfe" * 5000  # not valid UTF-8 on purpose
IMAGE_MD5 = hashlib.md5(IMAGE).hexdigest()  # noqa: S324
OTHER_MD5 = "0" * 32
_MOD = "workflow_steps.upload_binary.executor"


def _device(device_id: str = "device-1", ip: str | None = "10.0.0.1/24") -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        primary_ip4=ip,
        network_driver="cisco_ios",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _config(**overrides: object) -> dict:
    config = {
        "credential_reference": "lab-ssh",
        "git_repository_id": 7,
        "source_path": "images/cat9k.bin",
        "file_system": "flash:",
    }
    config.update(overrides)
    return config


class FakeDevice:
    """A device's flash: answers dir / verify / delete and keeps the bytes it is sent."""

    def __init__(self, *, existing_md5: str | None = None, events: list[str] | None = None):
        self.md5 = existing_md5  # None = no such file
        self.events = events if events is not None else []
        self.uploads: list[dict] = []
        self.commands: list[str] = []
        self.read_timeouts: list[int | None] = []
        self.received: bytes | None = None
        self.corrupt_on_copy = False
        self.verify_after_copy: CommandResult | None = None  # overrides the answer after a copy
        self.delete_ok = True
        self.copy_result = FileTransferResult(success=True, file_transferred=True)
        self.upload_error: Exception | None = None
        self._copied = False

    async def upload_file(self, **kwargs):
        self.events.append("upload")
        self.uploads.append(kwargs)
        if self.upload_error is not None:
            raise self.upload_error
        if self.copy_result.success:
            self.received = Path(kwargs["local_path"]).read_bytes()
            sent = self.received + (b"!" if self.corrupt_on_copy else b"")
            self.md5 = hashlib.md5(sent).hexdigest()  # noqa: S324
            self._copied = True
        return self.copy_result

    async def send_commands(self, *, commands, read_timeout=None, **_kwargs):
        (command,) = commands
        self.commands.append(command)
        self.read_timeouts.append(read_timeout)
        if command.startswith("dir "):
            if self.md5 is None:
                return CommandResult(success=True, output="%Error opening flash:/x (No such file)")
            return CommandResult(success=True, output="Directory of flash:/x")
        if command.startswith("verify /md5"):
            if self._copied and self.verify_after_copy is not None:
                return self.verify_after_copy
            return CommandResult(success=True, output=f"verify /md5 (flash:x) = {self.md5}")
        if command.startswith("delete /force"):
            if self.delete_ok:
                self.md5 = None
            return CommandResult(
                success=self.delete_ok, output="", error=None if self.delete_ok else "no"
            )
        raise AssertionError(command)


class UploadBinaryExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.root = base / "repo"
        (self.root / "images").mkdir(parents=True)
        self.image = self.root / "images" / "cat9k.bin"
        self.image.write_bytes(IMAGE)
        self.scratch = base / "scratch"  # the snapshot lands here
        self.scratch.mkdir()
        patcher = patch.object(tempfile, "tempdir", str(self.scratch))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.events: list[str] = []
        self.git_call: tuple | None = None

    async def _run(
        self, config: dict, devices: dict[str, DeviceContext], fakes: dict | None = None
    ):
        """``fakes`` maps device host (``10.0.0.1``) to a FakeDevice; default: one empty flash."""
        fakes = fakes if fakes is not None else {"10.0.0.1": FakeDevice(events=self.events)}
        run = MagicMock()
        run.id = 1
        executor = self

        async def _fake_git_root(repository_id, stack, *, allow_stale=False, refresh=True):
            executor.git_call = (repository_id, allow_stale)
            stack.callback(lambda: executor.events.append("lease_closed"))
            return executor.root

        async def _upload(**kwargs):
            return await fakes[kwargs["host"]].upload_file(**kwargs)

        async def _send(**kwargs):
            return await fakes[kwargs["host"]].send_commands(**kwargs)

        with (
            patch(f"{_MOD}.object_session", return_value=MagicMock()),
            patch(f"{_MOD}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(f"{_MOD}.resolve_git_root", new=_fake_git_root),
            patch(f"{_MOD}.NetmikoService") as netmiko_cls,
        ):
            netmiko_cls.return_value.upload_file = AsyncMock(side_effect=_upload)
            netmiko_cls.return_value.send_commands = AsyncMock(side_effect=_send)
            outcomes = await execute(
                config=config,
                context=WorkflowContext(run_id="r", workflow_id="w", devices=devices),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="ub-1",
                device_sessions=MagicMock(),
            )
        return outcomes, fakes

    def _only(self, outcomes, name: str) -> DeviceContext:
        by_name = {o.name: o for o in outcomes}
        (device,) = by_name[name].context.devices.values()
        return device

    # -- the bytes -----------------------------------------------------------------------------

    async def test_sends_a_private_snapshot_not_the_checkout_file(self) -> None:
        outcomes, fakes = await self._run(_config(), {"device-1": _device()})
        fake = fakes["10.0.0.1"]

        self.assertEqual([o.name for o in outcomes], ["success"])
        kwargs = fake.uploads[0]
        self.assertNotEqual(kwargs["local_path"], str(self.image))
        self.assertEqual(Path(kwargs["local_path"]).parent, self.scratch)
        self.assertEqual(fake.received, IMAGE)
        self.assertEqual(kwargs["dest_file"], "cat9k.bin")  # default: basename of source_path
        self.assertEqual(kwargs["file_system"], "flash:")
        self.assertFalse(kwargs["inline_transfer"])  # never inline for a binary
        self.assertFalse(kwargs["overwrite"])
        self.assertIs(kwargs["verify_file"], False)  # verified by the step, with its own timeout
        self.assertEqual(self.git_call, (7, False))
        self.assertEqual(list(self.scratch.iterdir()), [])  # snapshot removed after the step

    async def test_the_repository_is_released_before_any_device_is_contacted(self) -> None:
        await self._run(_config(), {"device-1": _device()})
        self.assertLess(self.events.index("lease_closed"), self.events.index("upload"))

    async def test_summary_records_copy_and_both_checks(self) -> None:
        outcomes, fake = await self._run(_config(), {"device-1": _device()})
        rows = self._only(outcomes, "success").command_results["ub-1"]
        self.assertEqual(
            [row.command for row in rows],
            ["upload-binary", "verify /md5 flash:cat9k.bin"],
        )
        self.assertTrue(all(row.success for row in rows))
        self.assertIn(IMAGE_MD5, rows[1].summary)
        self.assertIn(str(len(IMAGE)), rows[0].summary)

    async def test_options_are_forwarded_including_the_read_timeout(self) -> None:
        _, fakes = await self._run(
            _config(
                destination_filename="new.bin",
                overwrite="true",
                allow_stale_repository=True,
                socket_timeout=60,
                read_timeout=450,
                network_driver_override="cisco_xe",
            ),
            {"device-1": _device()},
        )
        fake = fakes["10.0.0.1"]
        kwargs = fake.uploads[0]
        self.assertEqual(kwargs["dest_file"], "new.bin")
        self.assertEqual(kwargs["socket_timeout"], 60)
        self.assertEqual(kwargs["device_type"], "cisco_xe")
        self.assertEqual(fake.read_timeouts, [450, 450])  # dir, verify
        self.assertEqual(self.git_call, (7, True))

    # -- md5 before the upload ------------------------------------------------------------------

    async def test_expected_md5_match_goes_on(self) -> None:
        outcomes, _ = await self._run(
            _config(expected_md5=IMAGE_MD5.upper()), {"device-1": _device()}
        )
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_expected_md5_mismatch_fails_before_any_device_is_contacted(self) -> None:
        fake = FakeDevice(events=self.events)
        with self.assertRaisesRegex(ValueError, "expected"):
            await self._run(
                _config(expected_md5=OTHER_MD5), {"device-1": _device()}, {"10.0.0.1": fake}
            )
        self.assertEqual((fake.commands, fake.uploads), ([], []))
        self.assertIn("lease_closed", self.events)
        self.assertEqual(list(self.scratch.iterdir()), [])

    async def test_unusable_source_path_fails_the_step_and_releases_the_repository(self) -> None:
        for bad in ("../x.bin", "images/missing.bin", "images"):
            self.events.clear()
            fake = FakeDevice(events=self.events)
            with self.assertRaises(ValueError, msg=bad):
                await self._run(
                    _config(source_path=bad), {"device-1": _device()}, {"10.0.0.1": fake}
                )
            self.assertEqual((fake.commands, fake.uploads), ([], []))
            self.assertIn("lease_closed", self.events)
        self.assertEqual(list(self.scratch.iterdir()), [])

    # -- md5 after the upload -------------------------------------------------------------------

    async def test_corrupt_copy_is_deleted_and_the_device_fails(self) -> None:
        fake = FakeDevice(events=self.events)
        fake.corrupt_on_copy = True
        outcomes, _ = await self._run(_config(), {"device-1": _device()}, {"10.0.0.1": fake})

        failed = self._only(outcomes, "failure")
        error = failed.errors[-1]
        self.assertEqual(error.code, "verify_failed")
        self.assertIn("mismatch", error.message)
        self.assertIn("removed from the device", error.message)
        self.assertTrue(any(c.startswith("delete /force flash:cat9k.bin") for c in fake.commands))
        self.assertIsNone(fake.md5)
        rows = failed.command_results["ub-1"]
        self.assertFalse(rows[-1].success)  # the stored row never claims it was verified
        self.assertNotIn("verified", rows[-1].summary.replace("not verified", ""))

    async def test_verify_timeout_deletes_the_copy_as_well(self) -> None:
        fake = FakeDevice(events=self.events)
        fake.verify_after_copy = CommandResult(success=False, error="Pattern not detected")
        outcomes, _ = await self._run(_config(), {"device-1": _device()}, {"10.0.0.1": fake})
        error = self._only(outcomes, "failure").errors[-1]
        self.assertEqual(error.code, "verify_failed")
        self.assertIn("Pattern not detected", error.message)
        self.assertTrue(any(c.startswith("delete /force") for c in fake.commands))

    async def test_failed_delete_is_reported(self) -> None:
        fake = FakeDevice(events=self.events)
        fake.corrupt_on_copy = True
        fake.delete_ok = False
        outcomes, _ = await self._run(_config(), {"device-1": _device()}, {"10.0.0.1": fake})
        self.assertIn("could NOT be removed", self._only(outcomes, "failure").errors[-1].message)

    # -- a file that is already there -----------------------------------------------------------

    async def test_identical_file_is_not_copied_again(self) -> None:
        fake = FakeDevice(existing_md5=IMAGE_MD5, events=self.events)
        outcomes, _ = await self._run(_config(), {"device-1": _device()}, {"10.0.0.1": fake})
        self.assertEqual(fake.uploads, [])
        rows = self._only(outcomes, "success").command_results["ub-1"]
        self.assertIn("already present", rows[-1].summary)
        self.assertEqual([c for c in fake.commands if c.startswith("delete")], [])

    async def test_different_file_without_overwrite_fails_and_is_left_alone(self) -> None:
        fake = FakeDevice(existing_md5=OTHER_MD5, events=self.events)
        outcomes, _ = await self._run(_config(), {"device-1": _device()}, {"10.0.0.1": fake})
        error = self._only(outcomes, "failure").errors[-1]
        self.assertEqual(error.code, "file_exists")
        self.assertIn(OTHER_MD5, error.message)
        self.assertEqual(fake.uploads, [])
        self.assertEqual(fake.md5, OTHER_MD5)

    async def test_different_file_with_overwrite_is_replaced(self) -> None:
        fake = FakeDevice(existing_md5=OTHER_MD5, events=self.events)
        outcomes, _ = await self._run(
            _config(overwrite=True), {"device-1": _device()}, {"10.0.0.1": fake}
        )
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertTrue(fake.uploads[0]["overwrite"])
        self.assertEqual(fake.md5, IMAGE_MD5)

    async def test_existing_file_that_cannot_be_read_fails_the_device(self) -> None:
        fake = FakeDevice(existing_md5=OTHER_MD5, events=self.events)
        fake.verify_after_copy = None
        original = fake.send_commands

        async def _unreadable(*, commands, **kwargs):
            if commands[0].startswith("verify"):
                return CommandResult(success=True, output="%Error verifying")
            return await original(commands=commands, **kwargs)

        fake.send_commands = _unreadable
        outcomes, _ = await self._run(
            _config(overwrite=True), {"device-1": _device()}, {"10.0.0.1": fake}
        )
        self.assertEqual(self._only(outcomes, "failure").errors[-1].code, "verify_failed")
        self.assertEqual(fake.uploads, [])

    async def test_unclear_dir_answer_fails_the_device_before_any_copy(self) -> None:
        fake = FakeDevice(events=self.events)

        async def _odd(*, commands, **kwargs):
            return CommandResult(success=True, output="???")

        fake.send_commands = _odd
        outcomes, _ = await self._run(_config(), {"device-1": _device()}, {"10.0.0.1": fake})
        self.assertEqual(self._only(outcomes, "failure").errors[-1].code, "exists_check_failed")
        self.assertEqual(fake.uploads, [])

    # -- failures per device --------------------------------------------------------------------

    async def test_transfer_failure_fails_the_device_without_verifying(self) -> None:
        fake = FakeDevice(events=self.events)
        fake.copy_result = FileTransferResult(success=False, error="SCP disabled")
        outcomes, _ = await self._run(_config(), {"device-1": _device()}, {"10.0.0.1": fake})
        failed = self._only(outcomes, "failure")
        self.assertEqual(failed.errors[-1].code, "upload_failed")
        self.assertEqual(failed.errors[-1].message, "SCP disabled")
        self.assertFalse([c for c in fake.commands if c.startswith(("verify", "delete"))])

    async def test_driver_exception_fails_only_that_device_and_hides_its_text(self) -> None:
        bad = FakeDevice(events=self.events)
        bad.upload_error = ConnectionError("login failed for admin / secret")
        good = FakeDevice(events=self.events)
        outcomes, _ = await self._run(
            _config(),
            {"ok": _device("ok", "10.0.0.1/24"), "boom": _device("boom", "10.0.0.2/24")},
            {"10.0.0.1": good, "10.0.0.2": bad},
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["success"].context.devices), ["ok"])
        error = by_name["failure"].context.devices["boom"].errors[-1]
        self.assertEqual(error.code, "connectionerror")
        self.assertEqual(error.message, "ConnectionError")  # no driver text in the stored run

    async def test_device_without_host_fails(self) -> None:
        bare = _device(ip=None).model_copy(update={"hostname": None})
        outcomes, _ = await self._run(_config(), {"device-1": bare}, {})
        self.assertEqual(self._only(outcomes, "failure").errors[-1].code, "missing_host")
        self.assertEqual(self._only(outcomes, "failure").errors[-1].failure.kind, "bad_request")

    async def test_no_devices_touches_neither_git_nor_devices(self) -> None:
        outcomes, _ = await self._run(_config(), {}, {})
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertIsNone(self.git_call)
        self.assertEqual(list(self.scratch.iterdir()), [])

    # -- config ---------------------------------------------------------------------------------

    async def test_config_errors_raise(self) -> None:
        bad_configs = {
            "no source_path": _config(source_path=""),
            "no file_system": _config(file_system=""),
            "no repository": _config(git_repository_id=None),
            "text repository": _config(git_repository_id="x"),
            "bool repository": _config(git_repository_id=True),
            "fractional repository": _config(git_repository_id=7.9),
            "bad md5": _config(expected_md5="nothex"),
            "socket too low": _config(socket_timeout=4),
            "socket too high": _config(socket_timeout=301),
            "read too low": _config(read_timeout=4),
            "read too high": _config(read_timeout=601),
            "bad flag": _config(overwrite="ture"),
            "newline in name": _config(destination_filename="a.bin\nreload"),
            "space in name": _config(destination_filename="a b.bin"),
            "space in file system": _config(file_system="flash: x"),
        }
        for label, bad in bad_configs.items():
            with self.assertRaises(ValueError, msg=label):
                await self._run(bad, {"device-1": _device()})
        self.assertIsNone(self.git_call)

    async def test_basename_with_a_line_break_is_refused_too(self) -> None:
        with self.assertRaises(ValueError):
            await self._run(
                _config(source_path="images/a\nb.bin", destination_filename=""),
                {"device-1": _device()},
            )

    async def test_boundary_timeouts_are_accepted(self) -> None:
        for socket_timeout, read_timeout in ((5, 5), (300, 600)):
            self.events.clear()
            outcomes, _ = await self._run(
                _config(socket_timeout=socket_timeout, read_timeout=read_timeout),
                {"device-1": _device()},
            )
            self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_whole_number_repository_ids_are_accepted(self) -> None:
        for raw in (7, "7", 7.0):
            await self._run(_config(git_repository_id=raw), {"device-1": _device()})
            self.assertEqual(self.git_call, (7, False))
