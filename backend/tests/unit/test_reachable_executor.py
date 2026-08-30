"""Tests for workflow_steps/reachable/executor.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from icmplib import ICMPLibError

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from workflow_steps.reachable.executor import (
    _device_failure,
    _parse_positive_int,
    _parse_positive_number,
    execute,
)


def _ping_result(sent: int = 4, received: int = 4, avg_rtt: float = 1.2) -> MagicMock:
    r = MagicMock()
    r.packets_sent = sent
    r.packets_received = received
    r.avg_rtt = avg_rtt
    return r


def _device(did: str, *, ip: str | None = "10.0.0.1", hostname: str = "lab") -> DeviceContext:
    return DeviceContext(
        id=did, name=did, hostname=hostname, primary_ip4=ip,
        capabilities={Capability.IDENTITY}, status=DeviceStatus.OK,
    )


class ParseHelperTests(unittest.TestCase):
    def test_positive_int_default_and_errors(self) -> None:
        self.assertEqual(_parse_positive_int({}, "ping_count"), 4)
        with self.assertRaises(ValueError):
            _parse_positive_int({"ping_count": "abc"}, "ping_count")
        with self.assertRaises(ValueError):
            _parse_positive_int({"ping_count": 0}, "ping_count")

    def test_positive_number_default_and_errors(self) -> None:
        self.assertEqual(_parse_positive_number({}, "timeout_seconds"), 2.0)
        with self.assertRaises(ValueError):
            _parse_positive_number({"timeout_seconds": "x"}, "timeout_seconds")
        with self.assertRaises(ValueError):
            _parse_positive_number({"timeout_seconds": 0}, "timeout_seconds")

    def test_device_failure_appends_error_and_marks_failed(self) -> None:
        failed = _device_failure(_device("d1"), node_id="n", code="c", message="m")
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "c")


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


_PING = "workflow_steps.reachable.executor.async_ping"


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def _run_execute(self, devices: dict, config: dict) -> list:
        return await execute(
            config=config,
            context=WorkflowContext(run_id="r", workflow_id="w", devices=devices),
            run=_run(), artifact_service=MagicMock(),
            node_id="reach-1", device_sessions=MagicMock(),
        )

    async def test_empty_devices_returns_both_outcomes(self) -> None:
        outcomes = await self._run_execute({}, {})
        self.assertEqual({o.name for o in outcomes}, {"success", "failure"})
        for o in outcomes:
            self.assertEqual(o.context.devices, {})

    async def test_required_replies_exceeding_ping_count_raises(self) -> None:
        with self.assertRaises(ValueError):
            await self._run_execute(
                {"d1": _device("d1")}, {"ping_count": 2, "required_replies": 3}
            )

    async def test_reachable_device_routes_to_success(self) -> None:
        with patch(_PING, new=AsyncMock(return_value=_ping_result(4, 4))):
            outcomes = await self._run_execute({"d1": _device("d1")}, {})
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["success"].context.devices), ["d1"])
        enriched = by_name["success"].context.devices["d1"]
        self.assertTrue(enriched.parsed["reach-1.reachability"]["reachable"])
        self.assertIn(Capability.PARSED, enriched.capabilities)
        self.assertEqual(
            by_name["success"].context.metadata["reach-1.reachability_counts"],
            {"success": 1, "failure": 0},
        )

    async def test_insufficient_replies_routes_to_failure_with_unreachable_error(self) -> None:
        with patch(_PING, new=AsyncMock(return_value=_ping_result(4, 0))):
            outcomes = await self._run_execute(
                {"d1": _device("d1")}, {"required_replies": 1}
            )
        by_name = {o.name: o for o in outcomes}
        failed = by_name["failure"].context.devices["d1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "unreachable")

    async def test_icmp_error_routes_to_failure(self) -> None:
        with patch(_PING, new=AsyncMock(side_effect=ICMPLibError("boom"))):
            outcomes = await self._run_execute({"d1": _device("d1")}, {})
        failed = {o.name: o for o in outcomes}["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "ping_error")

    async def test_device_without_host_routes_to_failure(self) -> None:
        outcomes = await self._run_execute(
            {"d1": _device("d1", ip=None, hostname="")}, {}
        )
        failed = {o.name: o for o in outcomes}["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "missing_host")


if __name__ == "__main__":
    unittest.main()
