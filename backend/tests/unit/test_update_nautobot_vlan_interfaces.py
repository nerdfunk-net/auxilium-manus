"""Tests for the "VLANs from interfaces" mode of update-nautobot-vlan."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.update_nautobot_vlan import executor as mod
from workflow_steps.update_nautobot_vlan.executor import _parse_config, execute

_LOC_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_LOC_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_V10 = "10000000-0000-0000-0000-000000000010"
_V20 = "20000000-0000-0000-0000-000000000020"
_V30 = "30000000-0000-0000-0000-000000000030"


def _vlan(vlan_id: str, vid: int, locations: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "id": vlan_id,
        "vid": vid,
        "name": f"V{vid}",
        "locations": [{"id": loc, "name": "x"} for loc in locations],
    }


def _device(did: str, location: str | None, interfaces: list | None) -> DeviceContext:
    bag: dict[str, Any] = {}
    if location:
        bag["location"] = {"id": location, "name": "loc"}
    if interfaces is not None:
        bag["interfaces"] = interfaces
    return DeviceContext(
        id=did,
        name=did,
        hostname=did,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        attribute_bags={"nautobot": bag},
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="r", workflow_id="w", devices={d.id: d for d in devices})


def _config(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {"nautobot_source_id": "src", "vlans_from_interfaces": True}
    cfg.update(overrides)
    return cfg


async def _run(config: dict, context: WorkflowContext, common: Any = None):
    common = common or MagicMock()
    if not isinstance(getattr(common, "update_vlan", None), AsyncMock):
        common.update_vlan = AsyncMock(return_value=True)
    if not isinstance(getattr(common, "missing_vlan_locations", None), AsyncMock):
        common.missing_vlan_locations = AsyncMock(side_effect=lambda _v, locs: list(locs))
    with patch.object(mod, "_bind_nautobot", return_value=mod._Bound(common=common)):
        outcomes = await execute(
            config=config,
            context=context,
            run=MagicMock(id="r"),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
    return {o.name: o.context for o in outcomes}, common


class ParseTests(unittest.TestCase):
    def test_no_vlan_selector_needed(self) -> None:
        parsed = _parse_config(_config())
        self.assertTrue(parsed.from_interfaces)
        self.assertFalse(parsed.dry_run)

    def test_dry_run_flag(self) -> None:
        self.assertTrue(_parse_config(_config(dry_run="true")).dry_run)

    def test_dry_run_is_refused_in_the_manual_mode_instead_of_writing(self) -> None:
        manual = {"nautobot_source_id": "src", "vlan_id": _V10, "status": "Active"}
        for flag in (True, "true"):
            with self.assertRaises(ValueError, msg=repr(flag)):
                _parse_config({**manual, "dry_run": flag})
        self.assertFalse(_parse_config({**manual, "dry_run": False}).dry_run)
        self.assertFalse(_parse_config({**manual, "dry_run": "false"}).dry_run)

    def test_other_fields_are_refused(self) -> None:
        for key in ("vlan_id", "vid", "vlan_group", "name", "status", "role", "locations"):
            with self.assertRaises(ValueError, msg=key):
                _parse_config(_config(**{key: "x"}))


class InterfaceModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_adds_device_location_to_every_vlan_once(self) -> None:
        interfaces = [
            {"untagged_vlan": _vlan(_V10, 10), "tagged_vlans": [_vlan(_V20, 20)]},
            {"untagged_vlan": _vlan(_V10, 10), "tagged_vlans": [_vlan(_V20, 20), _vlan(_V30, 30)]},
            {"untagged_vlan": None, "tagged_vlans": []},
        ]
        out, common = await _run(_config(), _context(_device("a", _LOC_A, interfaces)))
        calls = common.update_vlan.await_args_list
        self.assertEqual({c.args[0] for c in calls}, {_V10, _V20, _V30})
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual(call.args[1], {})
            self.assertEqual(call.kwargs["locations"], [_LOC_A])
            self.assertEqual(call.kwargs["locations_mode"], "add")
        self.assertIn("a", out["success"].devices)
        self.assertEqual(out["success"].metadata["n1.update_vlan_counts"]["updated"], 3)

    async def test_a_vlan_the_bag_shows_at_the_location_is_still_asked_of_nautobot(self) -> None:
        # The bag can be stale (the location was removed in Nautobot after it was read): the
        # decision is Nautobot's, update_vlan reads the assignments and POSTs only a missing one.
        interfaces = [{"untagged_vlan": _vlan(_V10, 10, (_LOC_A,)), "tagged_vlans": []}]
        common = MagicMock()
        common.update_vlan = AsyncMock(return_value=False)
        out, common = await _run(_config(), _context(_device("a", _LOC_A, interfaces)), common)
        common.update_vlan.assert_awaited_once()
        self.assertEqual(out["success"].metadata["n1.update_vlan_counts"]["unchanged"], 1)

    async def test_a_stale_bag_does_not_hide_a_missing_location_in_a_dry_run(self) -> None:
        interfaces = [{"untagged_vlan": _vlan(_V10, 10, (_LOC_A,)), "tagged_vlans": []}]
        out, common = await _run(_config(dry_run=True), _context(_device("a", _LOC_A, interfaces)))
        common.missing_vlan_locations.assert_awaited_once_with(_V10, [_LOC_A])
        preview = out["success"].devices["a"].dry_run_results["n1"]
        self.assertEqual([v["vid"] for v in preview["would_add_location"]], [10])
        self.assertEqual(preview["already_assigned"], 0)

    async def test_counts_are_per_pair_whatever_the_bag_says(self) -> None:
        # Ten devices at one site share a VLAN: one pair, counted once, whether the bag shows
        # the location or not.
        for bag_locations in ((), (_LOC_A,)):
            interfaces = [{"untagged_vlan": _vlan(_V10, 10, bag_locations), "tagged_vlans": []}]
            devices = [_device(f"d{i}", _LOC_A, interfaces) for i in range(10)]
            common = MagicMock()
            common.update_vlan = AsyncMock(return_value=False)
            out, _ = await _run(_config(), _context(*devices), common)
            counts = out["success"].metadata["n1.update_vlan_counts"]
            self.assertEqual((counts["updated"], counts["unchanged"]), (0, 1), bag_locations)

    async def test_same_pair_on_two_devices_is_written_once(self) -> None:
        interfaces = [{"untagged_vlan": _vlan(_V10, 10), "tagged_vlans": []}]
        ctx = _context(_device("a", _LOC_A, interfaces), _device("b", _LOC_A, interfaces))
        out, common = await _run(_config(), ctx)
        self.assertEqual(common.update_vlan.await_count, 1)
        self.assertEqual(set(out["success"].devices), {"a", "b"})

    async def test_different_locations_are_separate_writes(self) -> None:
        interfaces = [{"untagged_vlan": _vlan(_V10, 10), "tagged_vlans": []}]
        ctx = _context(_device("a", _LOC_A, interfaces), _device("b", _LOC_B, interfaces))
        _, common = await _run(_config(), ctx)
        self.assertEqual(common.update_vlan.await_count, 2)

    async def test_dry_run_writes_nothing_and_records_a_preview(self) -> None:
        interfaces = [{"untagged_vlan": _vlan(_V10, 10), "tagged_vlans": [_vlan(_V20, 20)]}]
        common = MagicMock()
        common.missing_vlan_locations = AsyncMock(
            side_effect=lambda vlan_id, locs: list(locs) if vlan_id == _V10 else []
        )
        out, common = await _run(
            _config(dry_run=True), _context(_device("a", _LOC_A, interfaces)), common
        )
        common.update_vlan.assert_not_awaited()
        device = out["success"].devices["a"]
        preview = device.dry_run_results["n1"]
        self.assertEqual([v["vid"] for v in preview["would_add_location"]], [10])
        self.assertEqual(preview["already_assigned"], 1)
        counts = out["success"].metadata["n1.update_vlan_counts"]
        self.assertTrue(counts["dry_run"])
        self.assertEqual(counts["updated"], 1)

    async def test_dry_run_asks_nautobot_not_the_bag(self) -> None:
        interfaces = [{"untagged_vlan": _vlan(_V10, 10), "tagged_vlans": []}]
        common = MagicMock()
        common.missing_vlan_locations = AsyncMock(return_value=[])
        out, _ = await _run(
            _config(dry_run=True), _context(_device("a", _LOC_A, interfaces)), common
        )
        common.missing_vlan_locations.assert_awaited_once_with(_V10, [_LOC_A])
        self.assertEqual(out["success"].metadata["n1.update_vlan_counts"]["updated"], 0)

    async def test_missing_location_fails_the_device(self) -> None:
        interfaces = [{"untagged_vlan": _vlan(_V10, 10), "tagged_vlans": []}]
        out, common = await _run(_config(), _context(_device("a", None, interfaces)))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "device_location_missing")
        common.update_vlan.assert_not_awaited()

    async def test_missing_interfaces_fails_the_device(self) -> None:
        out, _ = await _run(_config(), _context(_device("a", _LOC_A, None)))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "interfaces_missing")

    async def test_device_without_vlans_succeeds(self) -> None:
        out, common = await _run(_config(), _context(_device("a", _LOC_A, [{"name": "lo0"}])))
        self.assertIn("a", out["success"].devices)
        common.update_vlan.assert_not_awaited()

    async def test_failed_write_fails_only_the_devices_that_need_it(self) -> None:
        async def update(vlan_id, *_a, **_k):
            if vlan_id == _V20:
                raise RuntimeError("boom")
            return True

        common = MagicMock()
        common.update_vlan = AsyncMock(side_effect=update)
        a = _device("a", _LOC_A, [{"untagged_vlan": _vlan(_V10, 10), "tagged_vlans": []}])
        b = _device("b", _LOC_A, [{"untagged_vlan": _vlan(_V20, 20), "tagged_vlans": []}])
        out, _ = await _run(_config(), _context(a, b), common)
        self.assertIn("a", out["success"].devices)
        self.assertIn("b", out["failure"].devices)
        self.assertEqual(out["failure"].metadata["n1.update_vlan_counts"]["failed"], 1)

    async def test_invalid_vlan_id_in_bag_is_ignored(self) -> None:
        bad = {"id": "not-a-uuid", "vid": 5, "name": "x", "locations": []}
        out, common = await _run(
            _config(),
            _context(_device("a", _LOC_A, [{"untagged_vlan": bad, "tagged_vlans": []}])),
        )
        common.update_vlan.assert_not_awaited()
        self.assertIn("a", out["success"].devices)

    async def test_no_devices_makes_no_connection(self) -> None:
        out, common = await _run(_config(), _context())
        self.assertEqual(out["success"].devices, {})
        common.update_vlan.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
