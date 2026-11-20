"""Tests for VLANManager.update_vlan / find_vlans / name lookups."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.common.exceptions import NautobotAmbiguousMatchError, NautobotNotFoundError
from services.nautobot.managers.vlan_manager import (
    VLANManager,
    VlanPartialUpdateError,
    merge_locations,
)

_VLAN = "55555555-5555-5555-5555-555555555555"
_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_C = "cccccccc-cccc-cccc-cccc-cccccccccccc"
_R1 = "11111111-1111-1111-1111-111111111111"


def _manager(current: dict | None = None, assigned: dict[str, str] | None = None, pages=None):
    """A manager over a fake Nautobot: ``assigned`` maps location id -> assignment row id."""
    nautobot = MagicMock()
    calls: list[tuple[str, str, object]] = []

    async def rest_request(*, endpoint, method="GET", data=None):
        calls.append((method, endpoint, data))
        if method != "GET":
            return {}
        if "vlan-location-assignments" in endpoint:
            rows = [{"id": rid, "location": {"id": loc}} for loc, rid in (assigned or {}).items()]
            return {"results": rows, "next": None}
        if pages is not None:
            return pages.pop(0)
        return current

    nautobot.rest_request = AsyncMock(side_effect=rest_request)
    nautobot.calls = calls
    return VLANManager(nautobot, MagicMock()), nautobot


def _patches(nautobot) -> list[dict]:
    return [data for method, _, data in nautobot.calls if method == "PATCH"]


def _writes(nautobot, method: str) -> list[tuple[str, object]]:
    return [(endpoint, data) for m, endpoint, data in nautobot.calls if m == method]


class MissingLocationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_only_unassigned_locations_and_writes_nothing(self) -> None:
        manager, nautobot = _manager(assigned={_A: _R1})
        self.assertEqual(await manager.missing_locations(_VLAN, [_A, _B, _B]), [_B])
        self.assertEqual({m for m, _, _ in nautobot.calls}, {"GET"})

    async def test_rejects_a_non_uuid(self) -> None:
        manager, _ = _manager()
        with self.assertRaises(ValueError):
            await manager.missing_locations("nope", [_A])


class MergeLocationsTests(unittest.TestCase):
    def test_modes(self) -> None:
        self.assertEqual(merge_locations([_A], [_B, _B], "replace"), [_B])
        self.assertEqual(merge_locations([_A], [_B], "add"), [_A, _B])
        self.assertEqual(merge_locations([_A, _B], [_B], "remove"), [_A])
        self.assertEqual(merge_locations([_A], [_C], "remove"), [_A])


class UpdateVlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_differing_values_are_patched(self) -> None:
        current = {"name": "x", "description": "old", "status": {"id": "s1"}}
        manager, nautobot = _manager(current)
        changed = await manager.update_vlan(
            _VLAN, {"name": "x", "description": "new", "status": "s1"}
        )
        self.assertTrue(changed)
        self.assertEqual(_patches(nautobot), [{"description": "new"}])

    async def test_identical_values_send_nothing(self) -> None:
        manager, nautobot = _manager({"description": "d"}, {_A: _R1})
        changed = await manager.update_vlan(
            _VLAN, {"description": "d"}, locations=[_A], locations_mode="replace"
        )
        self.assertFalse(changed)
        self.assertEqual([m for m, _, _ in nautobot.calls if m != "GET"], [])

    async def test_locations_are_assignments_never_a_vlan_field(self) -> None:
        manager, nautobot = _manager({}, {_A: _R1})
        await manager.update_vlan(_VLAN, {}, locations=[_B], locations_mode="add")
        self.assertEqual(_patches(nautobot), [])
        self.assertEqual(
            _writes(nautobot, "POST"),
            [("ipam/vlan-location-assignments/", {"vlan": _VLAN, "location": _B})],
        )

    async def test_location_modes(self) -> None:
        cases = (
            ("replace", [_B], [_B], [_R1]),
            ("add", [_B], [_B], []),
            ("remove", [_A], [], [_R1]),
        )
        for mode, requested, added, removed in cases:
            manager, nautobot = _manager({}, {_A: _R1})
            self.assertTrue(
                await manager.update_vlan(_VLAN, {}, locations=requested, locations_mode=mode)
            )
            posts = [data["location"] for _, data in _writes(nautobot, "POST")]
            deletes = [endpoint.split("/")[-2] for endpoint, _ in _writes(nautobot, "DELETE")]
            self.assertEqual((posts, deletes), (added, removed), mode)

    async def test_add_existing_and_remove_missing_are_noops(self) -> None:
        manager, nautobot = _manager({}, {_A: _R1})
        self.assertFalse(await manager.update_vlan(_VLAN, {}, locations=[_A], locations_mode="add"))
        self.assertFalse(
            await manager.update_vlan(_VLAN, {}, locations=[_C], locations_mode="remove")
        )
        self.assertEqual([m for m, _, _ in nautobot.calls if m != "GET"], [])

    async def test_empty_locations_leave_them_alone(self) -> None:
        manager, nautobot = _manager({}, {_A: _R1})
        self.assertFalse(
            await manager.update_vlan(_VLAN, {}, locations=[], locations_mode="replace")
        )
        self.assertFalse(any("assignments" in e for _, e, _ in nautobot.calls))

    async def test_fields_and_locations_together_report_one_change(self) -> None:
        manager, nautobot = _manager({"description": "old"}, {})
        self.assertTrue(await manager.update_vlan(_VLAN, {"description": "new"}, locations=[_A]))
        self.assertEqual(_patches(nautobot), [{"description": "new"}])
        self.assertEqual(len(_writes(nautobot, "POST")), 1)

    async def test_uppercase_status_uuid_is_not_patched_again(self) -> None:
        manager, nautobot = _manager({"status": {"id": _A}, "role": {"id": _B}})
        changed = await manager.update_vlan(_VLAN, {"status": _A.upper(), "role": _B.upper()})
        self.assertFalse(changed)
        self.assertEqual(_patches(nautobot), [])

    async def test_failed_location_write_after_the_patch_is_reported_as_partial(self) -> None:
        manager, nautobot = _manager({"description": "old"}, {})
        inner = nautobot.rest_request.side_effect

        async def fail_post(*, endpoint, method="GET", data=None):
            if method == "POST":
                raise RuntimeError("boom")
            return await inner(endpoint=endpoint, method=method, data=data)

        nautobot.rest_request.side_effect = fail_post
        with self.assertRaises(VlanPartialUpdateError) as ctx:
            await manager.update_vlan(_VLAN, {"description": "new"}, locations=[_A])
        self.assertEqual(ctx.exception.applied, ("fields",))
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)

    async def test_failure_after_some_location_writes_is_partial(self) -> None:
        manager, nautobot = _manager({}, {_C: _R1})
        inner = nautobot.rest_request.side_effect

        async def fail_delete(*, endpoint, method="GET", data=None):
            if method == "DELETE":
                raise RuntimeError("boom")
            return await inner(endpoint=endpoint, method=method, data=data)

        nautobot.rest_request.side_effect = fail_delete
        with self.assertRaises(VlanPartialUpdateError) as ctx:
            await manager.update_vlan(_VLAN, {}, locations=[_A], locations_mode="replace")
        self.assertEqual(ctx.exception.applied, ("locations",))

    async def test_a_failure_before_anything_is_written_stays_a_plain_error(self) -> None:
        manager, nautobot = _manager({"description": "old"})
        inner = nautobot.rest_request.side_effect

        async def fail_patch(*, endpoint, method="GET", data=None):
            if method == "PATCH":
                raise RuntimeError("boom")
            return await inner(endpoint=endpoint, method=method, data=data)

        nautobot.rest_request.side_effect = fail_patch
        with self.assertRaises(RuntimeError):
            await manager.update_vlan(_VLAN, {"description": "new"})

    async def test_invalid_input(self) -> None:
        manager, _ = _manager({})
        with self.assertRaises(ValueError):
            await manager.update_vlan("nope", {})
        with self.assertRaises(ValueError):
            await manager.update_vlan(_VLAN, {}, locations_mode="merge")  # type: ignore[arg-type]


class LookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_find_vlans_returns_ids_and_passes_group(self) -> None:
        manager, nautobot = _manager(pages=[{"results": [{"id": _A}, {"id": _B}], "next": None}])
        self.assertEqual(await manager.find_vlans(100, _C), [_A, _B])
        endpoint = nautobot.rest_request.call_args.kwargs["endpoint"]
        self.assertIn("vid=100", endpoint)
        self.assertIn(f"vlan_group={_C}", endpoint)

    async def test_name_lookup(self) -> None:
        manager, _ = _manager(pages=[{"results": [{"id": _A, "name": "Berlin"}], "next": None}])
        self.assertEqual(await manager.resolve_location_id_strict("Berlin"), _A)

    async def test_uuid_is_checked_to_exist_and_lowercased(self) -> None:
        manager, nautobot = _manager({"id": _A})
        self.assertEqual(await manager.resolve_vlan_group_id(_A.upper()), _A)
        self.assertIn(f"ipam/vlan-groups/{_A}/", nautobot.calls[0][1])

    async def test_unknown_uuid_is_not_found(self) -> None:
        manager, nautobot = _manager({})
        nautobot.rest_request.side_effect = NautobotNotFoundError("gone")
        with self.assertRaises(ValueError):
            await manager.resolve_vlan_group_id(_A)

    async def test_name_match_is_case_insensitive(self) -> None:
        manager, nautobot = _manager(
            pages=[{"results": [{"id": _A, "name": "Berlin"}], "next": None}]
        )
        self.assertEqual(await manager.resolve_location_id_strict("berlin"), _A)
        self.assertIn("name__ic=berlin", nautobot.calls[0][1])

    async def test_a_partial_match_is_not_accepted(self) -> None:
        manager, _ = _manager(
            pages=[{"results": [{"id": _A, "name": "Berlin Mitte"}], "next": None}]
        )
        with self.assertRaises(ValueError):
            await manager.resolve_location_id_strict("Berlin")

    async def test_exact_case_wins_over_other_case(self) -> None:
        rows = [{"id": _A, "name": "berlin"}, {"id": _B, "name": "Berlin"}]
        manager, _ = _manager(pages=[{"results": rows, "next": None}])
        self.assertEqual(await manager.resolve_location_id_strict("Berlin"), _B)
        manager, _ = _manager(pages=[{"results": rows, "next": None}])
        with self.assertRaises(NautobotAmbiguousMatchError):
            await manager.resolve_location_id_strict("BERLIN")

    async def test_unknown_and_ambiguous_names(self) -> None:
        manager, _ = _manager(pages=[{"results": [], "next": None}])
        with self.assertRaises(ValueError):
            await manager.resolve_vlan_group_id("x")
        manager, _ = _manager(
            pages=[{"results": [{"id": _A, "name": "x"}, {"id": _B, "name": "x"}], "next": None}]
        )
        with self.assertRaises(NautobotAmbiguousMatchError):
            await manager.resolve_location_id_strict("x")
