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
    instances: list[FakeSession] = []

    def __init__(
        self, *, host: str, device_type: str, username: str, password: str, keepalive: int = 30
    ) -> None:
        self.host = host
        self.connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        FakeSession.instances.append(self)

    def connect(self, *, privileged: bool = True) -> None:
        self.connect_calls += 1
        self.connected = True

    def disconnect(self) -> None:
        if self.connected:
            self.disconnect_calls += 1
        self.connected = False

    def is_alive(self) -> bool:
        return self.connected

    def send_commands(self, commands: list[str], *, use_textfsm: bool = False) -> CommandResult:
        return CommandResult(
            success=True, output="ok", command_outputs={c: "ok" for c in commands}
        )


class NetmikoServicePoolReuseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeSession.instances = []

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

    async def test_test_login_leaves_pooled_session_open(self) -> None:
        with patch("services.network.netmiko.session_pool.NetmikoDeviceSession", FakeSession):
            pool = DeviceSessionPool(max_workers=2)
            service = NetmikoService(pool=pool)

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

            pooled_entry = next(iter(pool._sessions.values()))
            self.assertEqual(pooled_entry.session.connect_calls, 1)

            alive = await service.test_login(
                host="10.0.0.1",
                network_driver="cisco_ios",
                platform=None,
                username="admin",
                password="secret",
                credential_reference="lab-ssh",
            )

            self.assertTrue(alive)
            self.assertEqual(len(FakeSession.instances), 2)
            self.assertTrue(pooled_entry.session.connected)
            self.assertEqual(pooled_entry.session.connect_calls, 1)
            self.assertEqual(pooled_entry.session.disconnect_calls, 0)

            probe_session = FakeSession.instances[-1]
            self.assertIsNot(probe_session, pooled_entry.session)
            self.assertFalse(probe_session.connected)
            self.assertEqual(probe_session.disconnect_calls, 1)
            await pool.close()


if __name__ == "__main__":
    unittest.main()
