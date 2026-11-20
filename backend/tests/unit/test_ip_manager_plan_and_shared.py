"""Tests for IPManager.plan_ip_update, update_ip_address(dry_run) and shared_ip_ids."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.managers.ip_manager import IPManager

_IP = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_IP2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_STATUS = "44444444-4444-4444-4444-444444444444"
_IF1 = "10000000-0000-0000-0000-000000000001"
_IF_OTHER = "20000000-0000-0000-0000-000000000009"
# Letters in the id, so that changing its case really changes the text.
_IF_LETTERS = "abcdef00-aaaa-bbbb-cccc-000000000001"
_IF_OTHER_LETTERS = "fedcba00-dddd-eeee-ffff-000000000009"
_PARENT_A = "77777777-7777-7777-7777-777777777777"
_PARENT_B = "88888888-8888-8888-8888-888888888888"


def _manager(current: dict | None = None, routes: dict[str, dict] | None = None):
    nautobot = MagicMock()
    calls: list[tuple[str, str, object]] = []

    async def rest_request(*, endpoint, method="GET", data=None):
        calls.append((method, endpoint, data))
        for needle, response in (routes or {}).items():
            if needle in endpoint:
                return response
        return current if current is not None else {}

    nautobot.rest_request = AsyncMock(side_effect=rest_request)
    nautobot.calls = calls
    return IPManager(nautobot, MagicMock(), MagicMock()), nautobot


def _patches(nautobot) -> list[object]:
    return [data for method, _, data in nautobot.calls if method == "PATCH"]


_CURRENT = {
    "status": {"id": _STATUS},
    "description": "old",
    "dns_name": "Host.Example.Org",
    "host": "10.0.0.5",
    "parent": {"id": _PARENT_A},
}


class PlanIpUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_only_the_differences_and_writes_nothing(self) -> None:
        manager, nautobot = _manager(_CURRENT)
        changes = await manager.plan_ip_update(
            _IP, {"status": _STATUS, "description": "new", "dns_name": "host.example.org"}
        )
        self.assertEqual(changes, {"description": "new"})
        self.assertEqual(_patches(nautobot), [])

    async def test_a_namespace_move_shows_up_as_parent(self) -> None:
        manager, _ = _manager(_CURRENT)
        find_parent = AsyncMock(return_value=_PARENT_B)
        changes = await manager.plan_ip_update(_IP, {}, find_parent=find_parent)
        find_parent.assert_awaited_once_with("10.0.0.5")
        self.assertEqual(changes, {"parent": _PARENT_B})

    async def test_rejects_a_non_uuid(self) -> None:
        manager, _ = _manager(_CURRENT)
        with self.assertRaises(ValueError):
            await manager.plan_ip_update("nope", {"description": "x"})


class UpdateIpAddressDryRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_reports_a_change_without_patching(self) -> None:
        manager, nautobot = _manager(_CURRENT)
        self.assertTrue(await manager.update_ip_address(_IP, {"description": "new"}, dry_run=True))
        self.assertEqual(_patches(nautobot), [])

    async def test_dry_run_reports_no_change(self) -> None:
        manager, _ = _manager(_CURRENT)
        self.assertFalse(await manager.update_ip_address(_IP, {"description": "old"}, dry_run=True))

    async def test_a_normal_run_still_patches_only_the_differences(self) -> None:
        manager, nautobot = _manager(_CURRENT)
        self.assertTrue(
            await manager.update_ip_address(_IP, {"description": "new", "status": _STATUS})
        )
        self.assertEqual(_patches(nautobot), [{"description": "new"}])


def _assignment(ip: str, interface: str | None, vm: str | None = None) -> dict:
    return {
        "ip_address": {"id": ip},
        "interface": interface and {"id": interface},
        "vm_interface": vm,
    }


class SharedIpIdsTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_an_address_held_elsewhere_is_shared(self) -> None:
        manager, _ = _manager(
            routes={
                f"ip_address={_IP}": {"results": [_assignment(_IP, _IF1)]},
                f"ip_address={_IP2}": {
                    "results": [_assignment(_IP2, _IF1), _assignment(_IP2, _IF_OTHER)]
                },
            }
        )
        self.assertEqual(await manager.shared_ip_ids([_IP, _IP2], {_IF1}), {_IP2})

    async def test_vm_interface_counts_as_shared(self) -> None:
        manager, _ = _manager(
            routes={f"ip_address={_IP}": {"results": [_assignment(_IP, _IF1, vm="vm-if")]}}
        )
        self.assertEqual(await manager.shared_ip_ids([_IP], {_IF1}), {_IP})

    async def test_an_unconfirmed_address_counts_as_shared(self) -> None:
        manager, _ = _manager(routes={f"ip_address={_IP}": {"results": []}})
        self.assertEqual(await manager.shared_ip_ids([_IP], {_IF1}), {_IP})

    async def test_interface_ids_are_compared_without_regard_to_case(self) -> None:
        # The caller's ids (from an attribute bag) and Nautobot's answer need not agree in case.
        for own, reported in (
            (_IF_LETTERS.upper(), _IF_LETTERS),
            (_IF_LETTERS, _IF_LETTERS.upper()),
        ):
            manager, _ = _manager(
                routes={f"ip_address={_IP}": {"results": [_assignment(_IP, reported)]}}
            )
            self.assertEqual(await manager.shared_ip_ids([_IP], {own}), set(), (own, reported))

    async def test_a_foreign_interface_is_still_shared_whatever_its_case(self) -> None:
        manager, _ = _manager(
            routes={
                f"ip_address={_IP}": {
                    "results": [
                        _assignment(_IP, _IF_LETTERS),
                        _assignment(_IP, _IF_OTHER_LETTERS.upper()),
                    ]
                }
            }
        )
        self.assertEqual(await manager.shared_ip_ids([_IP], {_IF_LETTERS.upper()}), {_IP})

    async def test_no_addresses_makes_no_request(self) -> None:
        manager, nautobot = _manager()
        self.assertEqual(await manager.shared_ip_ids([], {_IF1}), set())
        nautobot.rest_request.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
