"""Unit tests for services/nautobot/devices/cable_normalize.py."""

from __future__ import annotations

import copy
import unittest

from services.nautobot.devices.cable_normalize import normalize_cables

_LOCAL = {"id": "dev-1", "name": "lab"}
_FAR = {"id": "if-2", "name": "Ethernet0/1", "device": {"id": "dev-2", "name": "switch"}}


def _legacy_bag() -> dict:
    return {
        "id": "dev-1",
        "name": "lab",
        "interfaces": [
            {
                "id": "if-1",
                "name": "Ethernet0/0",
                "cable": {"id": "c1", "label": "", "status": {"name": "Connected"}},
                "connected_endpoint": {"__typename": "InterfaceType", **_FAR},
            },
            {"id": "if-3", "name": "Ethernet0/3", "cable": None, "connected_endpoint": None},
        ],
    }


class NormalizeCablesTests(unittest.TestCase):
    def test_legacy_gets_interfaces_and_far_end_and_keeps_original(self) -> None:
        bag = _legacy_bag()
        before = copy.deepcopy(bag)
        out = normalize_cables(bag)
        self.assertEqual(bag, before)  # input untouched
        iface = out["interfaces"][0]
        self.assertEqual(iface["connected_endpoint"], bag["interfaces"][0]["connected_endpoint"])
        self.assertEqual(iface["cable"]["status"], {"name": "Connected"})
        self.assertEqual(
            iface["cable"]["interfaces"],
            [{"id": "if-1", "name": "Ethernet0/0", "device": _LOCAL}, _FAR],
        )
        self.assertEqual(iface["cable"]["far_end"], _FAR)
        self.assertIsNone(out["interfaces"][1]["cable"])

    def test_v32_keeps_interfaces_and_adds_far_end(self) -> None:
        ends = [{"id": "if-1", "name": "Ethernet0/0", "device": _LOCAL}, _FAR]
        bag = {
            "id": "dev-1",
            "name": "lab",
            "interfaces": [
                {"id": "if-1", "name": "Ethernet0/0", "cable": {"id": "c1", "interfaces": ends}}
            ],
        }
        cable = normalize_cables(bag)["interfaces"][0]["cable"]
        self.assertEqual(cable["interfaces"], ends)
        self.assertEqual(cable["far_end"], _FAR)

    def test_far_end_none_when_several_or_no_other_end(self) -> None:
        several = [{"id": "if-1", "name": "a"}, {"id": "x", "name": "b"}, {"id": "y", "name": "c"}]
        bag = {"interfaces": [{"id": "if-1", "cable": {"interfaces": several}}]}
        self.assertIsNone(normalize_cables(bag)["interfaces"][0]["cable"]["far_end"])
        legacy = {
            "id": "d",
            "name": "n",
            "interfaces": [
                {"id": "if-1", "name": "a", "cable": {"id": "c"}, "connected_endpoint": None}
            ],
        }
        cable = normalize_cables(legacy)["interfaces"][0]["cable"]
        self.assertIsNone(cable["far_end"])
        self.assertEqual(len(cable["interfaces"]), 1)

    def test_non_interface_endpoint_is_not_a_far_end(self) -> None:
        bag = {
            "id": "d",
            "name": "n",
            "interfaces": [
                {
                    "id": "if-1",
                    "name": "a",
                    "cable": {"id": "c"},
                    "connected_endpoint": {"__typename": "CircuitTerminationType", "id": "ct"},
                }
            ],
        }
        self.assertIsNone(normalize_cables(bag)["interfaces"][0]["cable"]["far_end"])

    def test_bag_without_interfaces_is_returned_as_is(self) -> None:
        bag = {"id": "d"}
        self.assertEqual(normalize_cables(bag), bag)
