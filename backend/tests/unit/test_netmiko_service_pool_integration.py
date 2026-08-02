"""Integration test: NetmikoService against a real DeviceSessionPool reuses one
session across multiple calls with the same key — see the "normal linear run,
2 SSH steps, same credential" row of the lifecycle matrix in
doc/DURABLE_SSH_SESSION.md §6."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services.network.netmiko.connection import CommandResult
from services.network.netmiko.service import NetmikoService
from services.network.netmiko.session_pool import DeviceSessionPool


class FakeSession:
    def __init__(
        self, *, host: str, device_type: str, username: str, password: str, keepalive: int = 30
    ) -> None:
        self.host = host
        self.connected = False
        self.connect_calls = 0

    def connect(self, *, privileged: bool = True) -> None:
        self.connect_calls += 1
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def is_alive(self) -> bool:
        return self.connected

    def send_commands(self, commands: list[str], *, use_textfsm: bool = False) -> CommandResult:
        return CommandResult(
            success=True, output="ok", command_outputs={c: "ok" for c in commands}
        )


class NetmikoServicePoolReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_calls_same_key_reuse_one_session(self) -> None:
        with patch("services.network.netmiko.session_pool.NetmikoDeviceSession", FakeSession):
            pool = DeviceSessionPool(max_workers=2)
            service = NetmikoService(pool=pool)

            for _ in range(2):
                result = await service.send_commands(
                    host="10.0.0.1",
                    network_driver="cisco_ios",
                    platform=None,
                    username="admin",
                    password="secret",
                    commands=["show version"],
                    credential_reference="lab-ssh",
                )
                self.assertTrue(result.success)

            entry = next(iter(pool._sessions.values()))
            self.assertEqual(entry.session.connect_calls, 1)
            await pool.close()

    async def test_different_credential_reference_gets_its_own_session(self) -> None:
        with patch("services.network.netmiko.session_pool.NetmikoDeviceSession", FakeSession):
            pool = DeviceSessionPool(max_workers=2)
            service = NetmikoService(pool=pool)

            for credential_reference in ("lab-ssh", "other-ssh"):
                await service.send_commands(
                    host="10.0.0.1",
                    network_driver="cisco_ios",
                    platform=None,
                    username="admin",
                    password="secret",
                    commands=["show version"],
                    credential_reference=credential_reference,
                )

            self.assertEqual(len(pool._sessions), 2)
            await pool.close()


if __name__ == "__main__":
    unittest.main()
