"""A probe that runs out of time keeps the hops read so far and is interrupted."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.network.netmiko.connection import NetmikoDeviceSession


def _session(reads: list[str]) -> tuple[NetmikoDeviceSession, MagicMock]:
    session = NetmikoDeviceSession.__new__(NetmikoDeviceSession)
    conn = MagicMock()
    conn.base_prompt = "sw1"
    conn.normalize_cmd.side_effect = lambda c: c + "\n"
    conn.read_channel.side_effect = [*reads, *([""] * 500)]
    session.connect = MagicMock()  # type: ignore[method-assign]
    session.__dict__["_conn"] = conn
    session.host = "10.0.0.1"
    return session, conn


class InterruptibleTests(unittest.TestCase):
    def _run(self, reads: list[str], timeout: int):
        session, conn = _session(reads)
        with (
            patch.object(NetmikoDeviceSession, "connection", conn),
            patch("services.network.netmiko.connection.time.sleep"),
        ):
            return session.send_commands(
                ["traceroute 10.9.9.9"], read_timeout=timeout, interrupt_on_timeout=True
            ), conn

    def test_finished_probe_is_a_success(self) -> None:
        reads = ["traceroute 10.9.9.9\r\n 1 10.0.0.2 1 ms\r\nsw1#"]
        result, conn = self._run(reads, 5)
        self.assertTrue(result.success)
        self.assertEqual(result.output, " 1 10.0.0.2 1 ms")
        conn.write_channel.assert_called_once()

    def test_timeout_keeps_hops_and_interrupts(self) -> None:
        reads = ["traceroute 10.9.9.9\r\n 1 10.0.0.2 1 ms\r\n 2 * * *\r\n"]
        clock = iter([0.0, 1.0, 2.0, 99.0, 100.0, 101.0, 200.0, 201.0, 202.0, 203.0])
        with patch(
            "services.network.netmiko.connection.time.monotonic",
            side_effect=lambda: next(clock, 1000.0),
        ):
            result, conn = self._run(reads, 10)
        self.assertFalse(result.success)
        self.assertIn("2 * * *", result.output)
        self.assertIn("interrupted", result.error or "")
        conn.write_channel.assert_any_call("\x1e\x03")
