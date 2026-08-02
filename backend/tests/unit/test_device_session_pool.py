"""Tests for DeviceSessionPool (see doc/DURABLE_SSH_SESSION.md §4, §8).

Uses a fake NetmikoDeviceSession (patched in for
``services.network.netmiko.session_pool.NetmikoDeviceSession``) so these are
pure unit tests with no real SSH/paramiko involved.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from services.network.netmiko.session_pool import DeviceSessionPool


class FakeSession:
    """Records connect/disconnect/op calls; no real network I/O."""

    def __init__(
        self,
        *,
        host: str,
        device_type: str,
        username: str,
        password: str,
        keepalive: int = 30,
    ) -> None:
        self.host = host
        self.device_type = device_type
        self.username = username
        self.password = password
        self.connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.alive = True
        self.disconnect_error: Exception | None = None
        self.config_mode_after_op = False
        self.check_config_mode_calls = 0

    def connect(self, *, privileged: bool = True) -> None:
        self.connect_calls += 1
        self.connected = True

    def disconnect(self) -> None:
        if not self.connected:
            return
        self.disconnect_calls += 1
        self.connected = False
        if self.disconnect_error is not None:
            raise self.disconnect_error

    def is_alive(self) -> bool:
        return self.connected and self.alive

    def check_config_mode(self) -> bool:
        self.check_config_mode_calls += 1
        return self.config_mode_after_op


def _patch_session_cls():
    return patch("services.network.netmiko.session_pool.NetmikoDeviceSession", FakeSession)


class DeviceSessionPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_session_for_same_key(self) -> None:
        with _patch_session_cls():
            pool = DeviceSessionPool(max_workers=2)
            calls: list[str] = []

            async def _call() -> None:
                await pool.run_on_device(
                    host="10.0.0.1",
                    device_type="cisco_ios",
                    credential_reference="admin-cred",
                    username="admin",
                    password="secret",
                    op=lambda session: calls.append(session.host),
                )

            await _call()
            await _call()

            entry = next(iter(pool._sessions.values()))
            self.assertEqual(entry.session.connect_calls, 1)
            self.assertEqual(len(calls), 2)
            await pool.close()

    async def test_distinct_sessions_per_credential_reference(self) -> None:
        with _patch_session_cls():
            pool = DeviceSessionPool(max_workers=2)

            for credential_reference in ("admin-cred", "other-cred"):
                await pool.run_on_device(
                    host="10.0.0.1",
                    device_type="cisco_ios",
                    credential_reference=credential_reference,
                    username="admin",
                    password="secret",
                    op=lambda session: None,
                )

            self.assertEqual(len(pool._sessions), 2)
            for entry in pool._sessions.values():
                self.assertEqual(entry.session.connect_calls, 1)
            await pool.close()

    async def test_reconnects_when_not_alive(self) -> None:
        with _patch_session_cls():
            pool = DeviceSessionPool(max_workers=2)
            kwargs = {
                "host": "10.0.0.1",
                "device_type": "cisco_ios",
                "credential_reference": "admin-cred",
                "username": "admin",
                "password": "secret",
            }

            await pool.run_on_device(**kwargs, op=lambda session: None)
            entry = next(iter(pool._sessions.values()))
            entry.session.alive = False

            await pool.run_on_device(**kwargs, op=lambda session: None)

            self.assertEqual(entry.session.connect_calls, 2)
            self.assertEqual(entry.session.disconnect_calls, 1)
            self.assertEqual(pool.stats()["reconnects"], 1)
            await pool.close()

    async def test_suspend_disconnects_but_pool_survives(self) -> None:
        with _patch_session_cls():
            pool = DeviceSessionPool(max_workers=2)
            kwargs = {
                "host": "10.0.0.1",
                "device_type": "cisco_ios",
                "credential_reference": "admin-cred",
                "username": "admin",
                "password": "secret",
            }
            await pool.run_on_device(**kwargs, op=lambda session: None)
            entry = next(iter(pool._sessions.values()))

            await pool.suspend()
            self.assertEqual(entry.session.disconnect_calls, 1)
            self.assertFalse(entry.session.connected)

            # Session still marked not-alive after suspend -> reconnect on next use.
            entry.session.alive = False
            await pool.run_on_device(**kwargs, op=lambda session: None)
            self.assertEqual(entry.session.connect_calls, 2)
            await pool.close()

    async def test_close_is_idempotent_and_shuts_executor(self) -> None:
        with _patch_session_cls():
            pool = DeviceSessionPool(max_workers=2)
            await pool.run_on_device(
                host="10.0.0.1",
                device_type="cisco_ios",
                credential_reference="admin-cred",
                username="admin",
                password="secret",
                op=lambda session: None,
            )

            await pool.close()
            await pool.close()  # must not raise

            self.assertTrue(pool._executor._shutdown)

    async def test_concurrent_acquire_same_key_serializes(self) -> None:
        with _patch_session_cls():
            pool = DeviceSessionPool(max_workers=4)
            order: list[str] = []

            def _op(tag: str):
                def _run(session) -> None:
                    order.append(f"{tag}-start")
                    order.append(f"{tag}-end")

                return _run

            kwargs = {
                "host": "10.0.0.1",
                "device_type": "cisco_ios",
                "credential_reference": "admin-cred",
                "username": "admin",
                "password": "secret",
            }

            await asyncio.gather(
                pool.run_on_device(**kwargs, op=_op("a")),
                pool.run_on_device(**kwargs, op=_op("b")),
            )

            self.assertEqual(len(pool._sessions), 1)
            entry = next(iter(pool._sessions.values()))
            self.assertEqual(entry.session.connect_calls, 1)
            # No interleaving: each op's start must be immediately followed by its own end.
            self.assertIn(order, [
                ["a-start", "a-end", "b-start", "b-end"],
                ["b-start", "b-end", "a-start", "a-end"],
            ])
            await pool.close()

    async def test_disabled_pool_matches_legacy_behavior(self) -> None:
        with _patch_session_cls():
            pool = DeviceSessionPool(max_workers=2, enabled=False)
            created: list[FakeSession] = []

            def _op(session: FakeSession):
                created.append(session)

            kwargs = {
                "host": "10.0.0.1",
                "device_type": "cisco_ios",
                "credential_reference": "admin-cred",
                "username": "admin",
                "password": "secret",
            }
            await pool.run_on_device(**kwargs, op=_op)
            await pool.run_on_device(**kwargs, op=_op)

            self.assertEqual(len(pool._sessions), 0)
            self.assertEqual(len(created), 2)
            for session in created:
                self.assertEqual(session.connect_calls, 1)
                self.assertEqual(session.disconnect_calls, 1)
            await pool.close()

    async def test_suspend_never_raises(self) -> None:
        with _patch_session_cls():
            pool = DeviceSessionPool(max_workers=2)
            await pool.run_on_device(
                host="10.0.0.1",
                device_type="cisco_ios",
                credential_reference="admin-cred",
                username="admin",
                password="secret",
                op=lambda session: None,
            )
            entry = next(iter(pool._sessions.values()))
            entry.session.disconnect_error = RuntimeError("boom")

            await pool.suspend()  # must not raise
            await pool.close()

    async def test_config_mode_guard_debug_only(self) -> None:
        with _patch_session_cls():
            pool = DeviceSessionPool(max_workers=2)
            kwargs = {
                "host": "10.0.0.1",
                "device_type": "cisco_ios",
                "credential_reference": "admin-cred",
                "username": "admin",
                "password": "secret",
                "op": lambda session: None,
            }

            await pool.run_on_device(**kwargs)
            entry = next(iter(pool._sessions.values()))
            self.assertEqual(entry.session.check_config_mode_calls, 0)

            await pool.run_on_device(**kwargs, debug=True)
            self.assertEqual(entry.session.check_config_mode_calls, 1)
            await pool.close()


if __name__ == "__main__":
    unittest.main()
