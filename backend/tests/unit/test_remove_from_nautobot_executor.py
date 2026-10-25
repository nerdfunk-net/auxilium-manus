"""Tests for workflow_steps/remove_from_nautobot/executor.py."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.nautobot.common.exceptions import NautobotAPIError, NautobotNotFoundError
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.remove_from_nautobot import executor as mod
from workflow_steps.remove_from_nautobot.executor import _parse_config, execute

_DEVICE_UUID = "11111111-1111-1111-1111-111111111111"
_OTHER_UUID = "22222222-2222-2222-2222-222222222222"
_IP_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_IP_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_IP_SHARED = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _device(did: str = _DEVICE_UUID, **overrides: Any) -> DeviceContext:
    return DeviceContext(
        id=did,
        name="sw1",
        hostname="sw1",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        **overrides,
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="r", workflow_id="w", devices={d.id: d for d in devices})


def _config(**overrides: Any) -> dict:
    cfg: dict[str, Any] = {"nautobot_source_id": "src-1", "device_id": "{device.id}"}
    cfg.update(overrides)
    return cfg


def _common(*, owned=(), shared=(), **overrides: Any) -> MagicMock:
    common = MagicMock()
    common.get_device_details = AsyncMock(return_value={"id": _DEVICE_UUID})
    common.list_device_ip_ids = AsyncMock(return_value=(list(owned), list(shared)))
    common.delete_ip_address = AsyncMock(return_value=None)
    common.delete_device = AsyncMock(return_value=None)
    for name, value in overrides.items():
        setattr(common, name, value)
    return common


async def _run(config: dict, context: WorkflowContext, common: MagicMock):
    bound = mod._Bound(common=common)
    with patch.object(mod, "_bind_nautobot", return_value=bound):
        outcomes = await execute(
            config=config,
            context=context,
            run=MagicMock(id="r"),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
    return {o.name: o.context for o in outcomes}


class ParseConfigTests(unittest.TestCase):
    def test_missing_source(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(nautobot_source_id=""))

    def test_missing_device_id(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(device_id=" "))

    def test_remove_ip_addresses_defaults_off(self) -> None:
        self.assertFalse(_parse_config(_config()).remove_ip_addresses)

    def test_remove_ip_addresses_string_spellings(self) -> None:
        self.assertTrue(_parse_config(_config(remove_ip_addresses="true")).remove_ip_addresses)
        self.assertFalse(_parse_config(_config(remove_ip_addresses="false")).remove_ip_addresses)

    def test_bad_flag_is_a_config_error(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(remove_ip_addresses="ture"))


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_removes_device_by_uuid_without_touching_ips(self) -> None:
        common = _common(owned=[_IP_A])
        out = await _run(_config(), _context(_device()), common)
        self.assertIn(_DEVICE_UUID, out["success"].devices)
        self.assertEqual(out["failure"].devices, {})
        common.delete_device.assert_awaited_once_with(_DEVICE_UUID)
        common.list_device_ip_ids.assert_not_awaited()
        common.delete_ip_address.assert_not_awaited()
        counts = out["success"].metadata["n1.remove_counts"]
        self.assertEqual(counts["devices_removed"], 1)
        self.assertEqual(counts["ips_removed"], 0)

    async def test_ips_are_removed_before_the_device(self) -> None:
        order: list[str] = []
        common = _common(owned=[_IP_A, _IP_B])
        common.delete_ip_address = AsyncMock(side_effect=lambda ip: order.append(f"ip:{ip}"))
        common.delete_device = AsyncMock(side_effect=lambda d: order.append(f"device:{d}"))
        out = await _run(_config(remove_ip_addresses=True), _context(_device()), common)
        self.assertEqual(order, [f"ip:{_IP_A}", f"ip:{_IP_B}", f"device:{_DEVICE_UUID}"])
        counts = out["success"].metadata["n1.remove_counts"]
        self.assertEqual(counts["ips_removed"], 2)

    async def test_shared_ip_is_kept_and_counted(self) -> None:
        common = _common(owned=[_IP_A], shared=[_IP_SHARED])
        out = await _run(_config(remove_ip_addresses=True), _context(_device()), common)
        deleted = [c.args[0] for c in common.delete_ip_address.await_args_list]
        self.assertEqual(deleted, [_IP_A])
        counts = out["success"].metadata["n1.remove_counts"]
        self.assertEqual(counts["ips_shared_skipped"], 1)
        self.assertIn(_DEVICE_UUID, out["success"].devices)

    async def test_ip_delete_failure_keeps_the_device(self) -> None:
        common = _common(owned=[_IP_A, _IP_B])
        common.delete_ip_address = AsyncMock(
            side_effect=[None, NautobotAPIError("boom", http_status=500)]
        )
        out = await _run(_config(remove_ip_addresses=True), _context(_device()), common)
        common.delete_device.assert_not_awaited()
        failed = out["failure"].devices[_DEVICE_UUID]
        self.assertEqual(failed.errors[-1].code, "ip_delete_failed")
        self.assertIn(_IP_B, failed.errors[-1].message)
        self.assertEqual(out["success"].devices, {})

    async def test_not_a_uuid_fails_without_calls(self) -> None:
        common = _common()
        dev = _device("not-a-uuid")
        out = await _run(_config(), _context(dev), common)
        self.assertEqual(out["failure"].devices["not-a-uuid"].errors[-1].code, "device_id_invalid")
        common.delete_device.assert_not_awaited()
        common.get_device_details.assert_not_awaited()

    async def test_fixed_uuid_in_config_wins_over_device_id(self) -> None:
        common = _common()
        await _run(_config(device_id=_OTHER_UUID), _context(_device()), common)
        common.get_device_details.assert_awaited_once_with(_OTHER_UUID)
        common.delete_device.assert_awaited_once_with(_OTHER_UUID)

    async def test_device_not_found(self) -> None:
        common = _common()
        common.get_device_details = AsyncMock(side_effect=NautobotNotFoundError("x"))
        out = await _run(_config(remove_ip_addresses=True), _context(_device()), common)
        self.assertEqual(out["failure"].devices[_DEVICE_UUID].errors[-1].code, "device_not_found")
        common.delete_device.assert_not_awaited()
        common.delete_ip_address.assert_not_awaited()

    async def test_device_delete_failure(self) -> None:
        common = _common()
        common.delete_device = AsyncMock(side_effect=NautobotAPIError("no", http_status=409))
        out = await _run(_config(), _context(_device()), common)
        self.assertIn(_DEVICE_UUID, out["failure"].devices)
        self.assertEqual(out["failure"].devices[_DEVICE_UUID].status, DeviceStatus.FAILED)

    async def test_sealed_secret_expression_is_refused(self) -> None:
        common = _common()
        with patch.object(
            mod, "resolve_update_field_expression", return_value=REDACTED_PLACEHOLDER
        ):
            out = await _run(_config(), _context(_device()), common)
        self.assertEqual(
            out["failure"].devices[_DEVICE_UUID].errors[-1].code, "device_id_is_secret"
        )
        common.delete_device.assert_not_awaited()

    async def test_unresolved_expression_fails_device(self) -> None:
        common = _common()
        with patch.object(mod, "resolve_update_field_expression", return_value=None):
            out = await _run(_config(), _context(_device()), common)
        self.assertEqual(
            out["failure"].devices[_DEVICE_UUID].errors[-1].code, "device_id_unresolved"
        )

    async def test_no_devices_returns_empty_outcomes_without_nautobot(self) -> None:
        with patch.object(mod, "_bind_nautobot", side_effect=AssertionError("bound")):
            outcomes = await execute(
                config=_config(),
                context=_context(),
                run=MagicMock(id="r"),
                artifact_service=MagicMock(),
                node_id="n1",
                device_sessions=MagicMock(),
            )
        self.assertEqual({o.name for o in outcomes}, {"success", "failure"})

    async def test_one_failure_does_not_stop_other_devices(self) -> None:
        common = _common()
        common.get_device_details = AsyncMock(
            side_effect=[NautobotNotFoundError("x"), {"id": _OTHER_UUID}]
        )
        out = await _run(_config(), _context(_device(_DEVICE_UUID), _device(_OTHER_UUID)), common)
        self.assertEqual(list(out["failure"].devices), [_DEVICE_UUID])
        self.assertEqual(list(out["success"].devices), [_OTHER_UUID])


class _FakeNautobot:
    """Stateful stand-in: an address is exclusive while no other existing device holds it."""

    def __init__(self, holders: dict[str, set[str]]) -> None:
        self.holders = holders  # ip id -> device ids that hold it
        self.devices = {d for ids in holders.values() for d in ids}
        self.deleted_ips: list[tuple[str, str]] = []
        self.current: dict[str, str] = {}

    def common(self) -> MagicMock:
        common = _common()

        async def details(device_id: str) -> dict:
            await asyncio.sleep(0)
            if device_id not in self.devices:
                raise NautobotNotFoundError("gone")
            return {"id": device_id}

        async def list_ids(device_id: str) -> tuple[list[str], list[str]]:
            await asyncio.sleep(0)
            owned, shared = [], []
            for ip, holders in self.holders.items():
                if device_id in holders:
                    others = (holders - {device_id}) & self.devices
                    (shared if others else owned).append(ip)
            return owned, shared

        async def delete_ip(ip_id: str) -> None:
            await asyncio.sleep(0)
            self.deleted_ips.append((ip_id, "x"))
            self.holders.pop(ip_id)

        async def delete_device(device_id: str) -> None:
            await asyncio.sleep(0)
            self.devices.discard(device_id)

        common.get_device_details = AsyncMock(side_effect=details)
        common.list_device_ip_ids = AsyncMock(side_effect=list_ids)
        common.delete_ip_address = AsyncMock(side_effect=delete_ip)
        common.delete_device = AsyncMock(side_effect=delete_device)
        return common


class SharedAddressInOneRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_address_shared_by_two_removed_devices_is_deleted_once_by_the_last(self) -> None:
        fake = _FakeNautobot({_IP_SHARED: {_DEVICE_UUID, _OTHER_UUID}, _IP_A: {_DEVICE_UUID}})
        out = await _run(
            _config(remove_ip_addresses=True),
            _context(_device(_DEVICE_UUID), _device(_OTHER_UUID)),
            fake.common(),
        )
        self.assertEqual(out["failure"].devices, {})
        self.assertEqual(sorted(ip for ip, _ in fake.deleted_ips), sorted([_IP_A, _IP_SHARED]))
        self.assertEqual(fake.devices, set())
        self.assertEqual(out["success"].metadata["n1.remove_counts"]["ips_removed"], 2)

    async def test_devices_run_one_at_a_time_when_removing_ips(self) -> None:
        active = peak = 0
        common = _common(owned=[])

        async def details(device_id: str) -> dict:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"id": device_id}

        common.get_device_details = AsyncMock(side_effect=details)
        await _run(
            _config(remove_ip_addresses=True),
            _context(_device(_DEVICE_UUID), _device(_OTHER_UUID)),
            common,
        )
        self.assertEqual(peak, 1)


class DeviceDeleteFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_device_delete_names_the_addresses_already_removed(self) -> None:
        common = _common(owned=[_IP_A, _IP_B])
        common.delete_device = AsyncMock(side_effect=NautobotAPIError("no", http_status=409))
        out = await _run(_config(remove_ip_addresses=True), _context(_device()), common)
        error = out["failure"].devices[_DEVICE_UUID].errors[-1]
        self.assertEqual(error.code, "device_delete_failed")
        self.assertIn(_IP_A, error.message)
        self.assertIn(_IP_B, error.message)
        self.assertEqual(out["failure"].metadata["n1.remove_counts"]["ips_removed"], 2)

    async def test_failed_device_delete_without_ip_removal_keeps_the_class_code(self) -> None:
        common = _common()
        common.delete_device = AsyncMock(side_effect=NautobotAPIError("no", http_status=409))
        out = await _run(_config(), _context(_device()), common)
        self.assertNotEqual(
            out["failure"].devices[_DEVICE_UUID].errors[-1].code, "device_delete_failed"
        )

    async def test_device_gone_at_delete_time_is_device_not_found(self) -> None:
        common = _common()
        common.delete_device = AsyncMock(side_effect=NautobotNotFoundError("gone"))
        out = await _run(_config(), _context(_device()), common)
        error = out["failure"].devices[_DEVICE_UUID].errors[-1]
        self.assertEqual(error.code, "device_not_found")

    async def test_device_gone_after_ips_were_removed_does_not_claim_nothing_was_removed(
        self,
    ) -> None:
        common = _common(owned=[_IP_A])
        common.delete_device = AsyncMock(side_effect=NautobotNotFoundError("gone"))
        out = await _run(_config(remove_ip_addresses=True), _context(_device()), common)
        error = out["failure"].devices[_DEVICE_UUID].errors[-1]
        self.assertEqual(error.code, "device_not_found")
        self.assertNotIn("nothing was removed", error.message)
        self.assertIn(_IP_A, error.message)


if __name__ == "__main__":
    unittest.main()
