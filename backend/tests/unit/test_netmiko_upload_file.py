"""Tests for NetmikoDeviceSession.upload_file / NetmikoService.upload_file."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.network.netmiko.connection import FileTransferResult, NetmikoDeviceSession
from services.network.netmiko.service import NetmikoService


def _session() -> NetmikoDeviceSession:
    return NetmikoDeviceSession(
        host="10.0.0.1",
        device_type="cisco_ios",
        username="admin",
        password="secret",
    )


class NetmikoDeviceSessionUploadFileTests(unittest.TestCase):
    def test_success_reports_transferred_and_verified(self) -> None:
        session = _session()
        with (
            patch("services.network.netmiko.connection.ConnectHandler"),
            patch("services.network.netmiko.connection.file_transfer") as file_transfer_mock,
        ):
            file_transfer_mock.return_value = {
                "file_transferred": True,
                "file_verified": True,
                "file_exists": False,
            }
            result = session.upload_file(
                local_path="/tmp/new-config.cfg",
                dest_file="new-config.cfg",
                file_system="bootflash:",
            )

        self.assertTrue(result.success)
        self.assertTrue(result.file_transferred)
        self.assertTrue(result.file_verified)
        self.assertFalse(result.file_exists)
        call_kwargs = file_transfer_mock.call_args.kwargs
        self.assertEqual(call_kwargs["source_file"], "/tmp/new-config.cfg")
        self.assertEqual(call_kwargs["dest_file"], "new-config.cfg")
        self.assertEqual(call_kwargs["file_system"], "bootflash:")
        self.assertEqual(call_kwargs["direction"], "put")
        self.assertFalse(call_kwargs["overwrite_file"])
        self.assertFalse(call_kwargs["inline_transfer"])
        self.assertEqual(call_kwargs["socket_timeout"], 10.0)

    def test_overwrite_and_inline_transfer_are_forwarded(self) -> None:
        session = _session()
        with (
            patch("services.network.netmiko.connection.ConnectHandler"),
            patch("services.network.netmiko.connection.file_transfer") as file_transfer_mock,
        ):
            file_transfer_mock.return_value = {
                "file_transferred": True,
                "file_verified": False,
                "file_exists": True,
            }
            result = session.upload_file(
                local_path="/tmp/new-config.cfg",
                dest_file="new-config.cfg",
                file_system="flash:",
                overwrite=True,
                inline_transfer=True,
                socket_timeout=30,
            )

        self.assertTrue(result.success)
        self.assertTrue(result.file_exists)
        self.assertFalse(result.file_verified)
        call_kwargs = file_transfer_mock.call_args.kwargs
        self.assertTrue(call_kwargs["overwrite_file"])
        self.assertTrue(call_kwargs["inline_transfer"])
        self.assertEqual(call_kwargs["socket_timeout"], 30)

    def test_transfer_error_is_captured(self) -> None:
        session = _session()
        with (
            patch("services.network.netmiko.connection.ConnectHandler"),
            patch("services.network.netmiko.connection.file_transfer") as file_transfer_mock,
        ):
            file_transfer_mock.side_effect = RuntimeError("SCP disabled on device")
            result = session.upload_file(
                local_path="/tmp/new-config.cfg",
                dest_file="new-config.cfg",
                file_system="bootflash:",
            )

        self.assertFalse(result.success)
        self.assertIn("SCP disabled on device", result.error or "")


class NetmikoServiceUploadFileTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_device_type_and_delegates_to_pool(self) -> None:
        pool = MagicMock()
        expected = FileTransferResult(success=True, file_transferred=True, file_verified=True)
        pool.run_on_device = AsyncMock(return_value=expected)
        service = NetmikoService(pool=pool)

        result = await service.upload_file(
            host="10.0.0.1",
            network_driver="cisco_ios",
            platform=None,
            username="admin",
            password="secret",
            local_path="/tmp/new-config.cfg",
            dest_file="new-config.cfg",
            file_system="bootflash:",
            overwrite=False,
            inline_transfer=False,
            socket_timeout=10,
            credential_reference="lab-ssh",
        )

        self.assertIs(result, expected)
        call_kwargs = pool.run_on_device.call_args.kwargs
        self.assertEqual(call_kwargs["device_type"], "cisco_ios")
        self.assertEqual(call_kwargs["credential_reference"], "lab-ssh")
        self.assertTrue(callable(call_kwargs["op"]))

    async def test_device_type_override_is_honored(self) -> None:
        pool = MagicMock()
        pool.run_on_device = AsyncMock(return_value=FileTransferResult(success=True))
        service = NetmikoService(pool=pool)

        await service.upload_file(
            host="10.0.0.1",
            network_driver="cisco_ios",
            platform=None,
            username="admin",
            password="secret",
            local_path="/tmp/new-config.cfg",
            dest_file="new-config.cfg",
            file_system="bootflash:",
            overwrite=False,
            inline_transfer=False,
            socket_timeout=10,
            credential_reference="lab-ssh",
            device_type="cisco_xe",
        )

        self.assertEqual(pool.run_on_device.call_args.kwargs["device_type"], "cisco_xe")


if __name__ == "__main__":
    unittest.main()
