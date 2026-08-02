"""Tests for shared Cisco ISE lookup helpers (workflow_steps/common/ise_lookup.py)."""

from __future__ import annotations

import ipaddress
import unittest

from workflow_steps.common.ise_lookup import device_ip_list_matches, ip_entry_matches


def _ip(value: str) -> ipaddress.IPv4Address:
    return ipaddress.IPv4Address(value)


class IpEntryMatchesTests(unittest.TestCase):
    def test_plain_host_exact_match(self) -> None:
        entry = {"ipaddress": "10.0.0.1", "mask": 32}
        self.assertTrue(ip_entry_matches(entry, _ip("10.0.0.1")))
        self.assertFalse(ip_entry_matches(entry, _ip("10.0.0.2")))

    def test_cidr_network_address_and_mask(self) -> None:
        entry = {"ipaddress": "192.168.178.0", "mask": 24}
        self.assertTrue(ip_entry_matches(entry, _ip("192.168.178.240")))
        self.assertFalse(ip_entry_matches(entry, _ip("192.168.179.1")))

    def test_cidr_embedded_directly_in_ipaddress_field(self) -> None:
        entry = {"ipaddress": "192.168.178.0/24"}
        self.assertTrue(ip_entry_matches(entry, _ip("192.168.178.240")))
        self.assertFalse(ip_entry_matches(entry, _ip("10.0.0.1")))

    def test_hyphen_range_last_octet_only(self) -> None:
        entry = {"ipaddress": "192.168.178.1-254", "mask": 32}
        self.assertTrue(ip_entry_matches(entry, _ip("192.168.178.240")))
        self.assertTrue(ip_entry_matches(entry, _ip("192.168.178.1")))
        self.assertTrue(ip_entry_matches(entry, _ip("192.168.178.254")))
        self.assertFalse(ip_entry_matches(entry, _ip("192.168.178.255")))
        self.assertFalse(ip_entry_matches(entry, _ip("192.168.179.5")))

    def test_hyphen_range_full_end_ip(self) -> None:
        entry = {"ipaddress": "192.168.178.10-192.168.178.20", "mask": 32}
        self.assertTrue(ip_entry_matches(entry, _ip("192.168.178.15")))
        self.assertFalse(ip_entry_matches(entry, _ip("192.168.178.25")))

    def test_wildcard_last_octet(self) -> None:
        entry = {"ipaddress": "192.168.178.*", "mask": 32}
        self.assertTrue(ip_entry_matches(entry, _ip("192.168.178.240")))
        self.assertFalse(ip_entry_matches(entry, _ip("192.168.179.1")))

    def test_wildcard_multiple_octets(self) -> None:
        entry = {"ipaddress": "10.*.*.*", "mask": 32}
        self.assertTrue(ip_entry_matches(entry, _ip("10.1.2.3")))
        self.assertFalse(ip_entry_matches(entry, _ip("11.1.2.3")))

    def test_malformed_entry_returns_false(self) -> None:
        self.assertFalse(ip_entry_matches({"ipaddress": "not-an-ip"}, _ip("10.0.0.1")))
        self.assertFalse(ip_entry_matches({}, _ip("10.0.0.1")))

    def test_empty_ipaddress_returns_false(self) -> None:
        self.assertFalse(ip_entry_matches({"ipaddress": ""}, _ip("10.0.0.1")))


class DeviceIpListMatchesTests(unittest.TestCase):
    def test_matches_when_any_entry_contains_target(self) -> None:
        detail = {
            "NetworkDeviceIPList": [
                {"ipaddress": "10.0.0.1", "mask": 32},
                {"ipaddress": "192.168.178.1-254", "mask": 32},
            ]
        }
        self.assertTrue(device_ip_list_matches(detail, _ip("192.168.178.100")))
        self.assertFalse(device_ip_list_matches(detail, _ip("172.16.0.1")))

    def test_empty_ip_list_returns_false(self) -> None:
        self.assertFalse(device_ip_list_matches({}, _ip("10.0.0.1")))


if __name__ == "__main__":
    unittest.main()
