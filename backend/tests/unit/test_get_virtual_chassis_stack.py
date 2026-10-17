"""Tests for the pure helpers of workflow_steps/get_virtual_chassis/stack.py."""

from __future__ import annotations

import unittest
from typing import Any

from models.workflow_context import Capability, DeviceStatus
from workflow_steps.get_virtual_chassis.stack import (
    build_stack_devices,
    matches_name,
    member_index,
    parse_settings,
    pick_master,
)

_NODE = "node-1"


def _member(
    name: str,
    position: int,
    *,
    master: bool = False,
    ip: str | None = None,
    serial: str = "SN",
) -> dict[str, Any]:
    return {
        "id": f"id-{name}",
        "name": name,
        "vc_position": position,
        "vc_priority": 15 if master else 1,
        "serial": serial,
        "device_type": {"model": "C9300-48P"},
        "platform": {"name": "Cisco IOS-XE", "network_driver": "cisco_xe"},
        "primary_ip4": {"address": ip} if ip else None,
        "vc_master_for": {"id": "vc-1", "name": "LAB.local.zz"} if master else None,
    }


def _vc(*, master_ip: str | None = "10.0.0.1/24") -> dict[str, Any]:
    return {
        "id": "vc-1",
        "name": "LAB.local.zz",
        "members": [
            _member("LAB.local.zz", 1, master=True, ip=master_ip, serial="SN1"),
            _member("LAB:2.local.zz", 2, serial="SN2"),
        ],
    }


class ParseSettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        s = parse_settings({})
        self.assertFalse(s.split_members)
        self.assertEqual(s.index_offset, -1)
        self.assertEqual(s.index_default, 0)
        self.assertEqual(s.attribute_bag, "virtual_chassis")
        self.assertEqual(s.index_key, "stack_index")
        self.assertEqual(s.name_match, "exact")

    def test_invalid_regex_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_regex"):
            parse_settings({"index_regex": "(unclosed"})

    def test_overlong_regex_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_regex"):
            parse_settings({"index_regex": "a" * 201})

    def test_empty_regex_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_regex"):
            parse_settings({"index_regex": "  "})

    def test_non_int_offset_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_offset"):
            parse_settings({"index_offset": "abc"})

    def test_bool_offset_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_offset"):
            parse_settings({"index_offset": True})

    def test_unknown_match_mode_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "name_match"):
            parse_settings({"name_match": "fuzzy"})

    def test_invalid_filter_regex_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "name_filter"):
            parse_settings({"name_match": "regex", "name_filter": "("})

    def test_reserved_bag_name_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "attribute_bag"):
            parse_settings({"attribute_bag": "parsed"})

    def test_blank_bag_name_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "attribute_bag"):
            parse_settings({"attribute_bag": " "})

    def test_dotted_key_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_key"):
            parse_settings({"index_key": "a.b"})

    def test_numeric_strings_are_accepted(self) -> None:
        s = parse_settings({"index_offset": "-2", "index_default": "5"})
        self.assertEqual((s.index_offset, s.index_default), (-2, 5))


class MemberIndexTests(unittest.TestCase):
    def test_master_without_marker_gets_default(self) -> None:
        self.assertEqual(member_index("LAB.local.zz", parse_settings({})), 0)

    def test_second_member_is_offset_to_one(self) -> None:
        self.assertEqual(member_index("LAB:2.local.zz", parse_settings({})), 1)

    def test_multi_digit(self) -> None:
        self.assertEqual(member_index("LAB:10.local.zz", parse_settings({})), 9)

    def test_custom_separator_and_no_offset(self) -> None:
        s = parse_settings({"index_regex": r"-sw(\d+)", "index_offset": 0})
        self.assertEqual(member_index("LAB-sw3.local.zz", s), 3)

    def test_custom_default(self) -> None:
        self.assertEqual(member_index("LAB.local.zz", parse_settings({"index_default": 7})), 7)

    def test_regex_without_group_uses_whole_match(self) -> None:
        s = parse_settings({"index_regex": r"\d+", "index_offset": 0})
        self.assertEqual(member_index("LAB2.local.zz", s), 2)

    def test_non_numeric_capture_falls_back_to_default(self) -> None:
        s = parse_settings({"index_regex": r":(\w)"})
        self.assertEqual(member_index("LAB:x.local.zz", s), 0)


class MatchesNameTests(unittest.TestCase):
    def test_empty_filter_matches_all(self) -> None:
        self.assertTrue(matches_name("anything", parse_settings({})))

    def test_exact(self) -> None:
        s = parse_settings({"name_filter": "LAB.local.zz"})
        self.assertTrue(matches_name("LAB.local.zz", s))
        self.assertFalse(matches_name("LAB.local.zz2", s))

    def test_contains_is_case_insensitive(self) -> None:
        s = parse_settings({"name_match": "contains", "name_filter": "lab"})
        self.assertTrue(matches_name("LAB.local.zz", s))
        self.assertFalse(matches_name("core.local.zz", s))

    def test_regex_uses_search(self) -> None:
        s = parse_settings({"name_match": "regex", "name_filter": r"^LAB\."})
        self.assertTrue(matches_name("LAB.local.zz", s))
        self.assertFalse(matches_name("xLAB.local.zz", s))


class PickMasterTests(unittest.TestCase):
    def test_prefers_vc_master_for(self) -> None:
        members = [_member("b", 1), _member("a", 2, master=True)]
        self.assertEqual(pick_master(members)["name"], "a")  # type: ignore[index]

    def test_falls_back_to_lowest_position(self) -> None:
        members = [_member("b", 2), _member("a", 1)]
        self.assertEqual(pick_master(members)["name"], "a")  # type: ignore[index]

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(pick_master([]))


class BuildUnsplitTests(unittest.TestCase):
    def test_one_device_per_stack(self) -> None:
        devices = build_stack_devices(_vc(), parse_settings({}), source_id="src", node_id=_NODE)
        self.assertEqual(len(devices), 1)
        dev = devices[0]
        self.assertEqual(dev.id, "id-LAB.local.zz")  # master's device id, not the VC id
        self.assertEqual(dev.name, "LAB.local.zz")
        self.assertEqual(dev.primary_ip4, "10.0.0.1/24")
        self.assertEqual(dev.hostname, "10.0.0.1")
        self.assertEqual(dev.network_driver, "cisco_xe")
        self.assertEqual(dev.source, "nautobot")
        self.assertEqual(dev.status, DeviceStatus.OK)
        self.assertIn(Capability.IDENTITY, dev.capabilities)

    def test_members_listed_in_bag(self) -> None:
        dev = build_stack_devices(_vc(), parse_settings({}), source_id="src", node_id=_NODE)[0]
        bag = dev.attribute_bags["virtual_chassis"]
        self.assertEqual(bag["vc_id"], "vc-1")
        self.assertEqual(bag["member_count"], 2)
        self.assertEqual([m["stack_index"] for m in bag["members"]], [0, 1])
        self.assertEqual([m["serial"] for m in bag["members"]], ["SN1", "SN2"])
        self.assertEqual(bag["members"][1]["device_type"], "C9300-48P")
        self.assertTrue(bag["members"][0]["is_master"])
        self.assertEqual(bag["master"]["name"], "LAB.local.zz")

    def test_custom_bag_and_key(self) -> None:
        s = parse_settings({"attribute_bag": "stack", "index_key": "idx"})
        dev = build_stack_devices(_vc(), s, source_id="src", node_id=_NODE)[0]
        self.assertIn("stack", dev.attribute_bags)
        self.assertEqual(dev.attribute_bags["stack"]["members"][1]["idx"], 1)


class BuildSplitTests(unittest.TestCase):
    def test_one_device_per_member_sharing_master_ip(self) -> None:
        s = parse_settings({"split_members": True})
        devices = build_stack_devices(_vc(), s, source_id="src", node_id=_NODE)
        self.assertEqual([d.name for d in devices], ["LAB.local.zz", "LAB:2.local.zz"])
        self.assertEqual({d.primary_ip4 for d in devices}, {"10.0.0.1/24"})
        self.assertEqual({d.hostname for d in devices}, {"10.0.0.1"})
        self.assertEqual([d.id for d in devices], ["id-LAB.local.zz", "id-LAB:2.local.zz"])

    def test_index_written_to_chosen_bag(self) -> None:
        s = parse_settings({"split_members": True, "attribute_bag": "stack", "index_key": "n"})
        devices = build_stack_devices(_vc(), s, source_id="src", node_id=_NODE)
        self.assertEqual([d.attribute_bags["stack"]["n"] for d in devices], [0, 1])
        second = devices[1].attribute_bags["stack"]
        self.assertEqual(second["serial"], "SN2")
        self.assertEqual(second["position"], 2)
        self.assertFalse(second["is_master"])
        self.assertEqual(second["master_name"], "LAB.local.zz")
        self.assertEqual(second["vc_name"], "LAB.local.zz")
        self.assertEqual(second["member_count"], 2)


class NoMasterIpTests(unittest.TestCase):
    def test_unsplit_marks_device_failed(self) -> None:
        devices = build_stack_devices(
            _vc(master_ip=None), parse_settings({}), source_id="src", node_id=_NODE
        )
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].status, DeviceStatus.FAILED)
        self.assertEqual(devices[0].errors[0].code, "no_primary_ip")
        self.assertEqual(devices[0].errors[0].node_id, _NODE)

    def test_split_marks_every_member_failed(self) -> None:
        devices = build_stack_devices(
            _vc(master_ip=None),
            parse_settings({"split_members": True}),
            source_id="src",
            node_id=_NODE,
        )
        self.assertEqual(len(devices), 2)
        self.assertTrue(all(d.status == DeviceStatus.FAILED for d in devices))

    def test_vc_without_members_yields_failed_stack_device(self) -> None:
        vc = {"id": "vc-9", "name": "EMPTY", "members": []}
        devices = build_stack_devices(vc, parse_settings({}), source_id="src", node_id=_NODE)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].id, "vc-9")
        self.assertEqual(devices[0].status, DeviceStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
