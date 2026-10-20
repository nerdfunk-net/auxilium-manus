"""Tests for workflow_steps/get_next_free_ip/pool.py."""

from __future__ import annotations

import unittest

from workflow_steps.get_next_free_ip.pool import (
    bare_address,
    free_addresses_from,
    parse_prefix,
    take,
    window_size,
)


def _avail(*hosts: int, base: str = "192.168.178", length: int = 24) -> list[dict]:
    return [{"ip_version": 4, "address": f"{base}.{h}/{length}"} for h in hosts]


class ParsePrefixTests(unittest.TestCase):
    def test_valid(self) -> None:
        self.assertEqual(str(parse_prefix(" 192.168.178.0/24 ")), "192.168.178.0/24")

    def test_host_address_with_length_gives_its_network(self) -> None:
        self.assertEqual(str(parse_prefix("192.168.178.240/24")), "192.168.178.0/24")
        self.assertEqual(str(parse_prefix("2001:db8::5/64")), "2001:db8::/64")

    def test_bare_address_is_not_a_prefix_but_is_detected(self) -> None:
        self.assertEqual(str(bare_address(" 192.168.178.240 ")), "192.168.178.240")
        self.assertIsNone(bare_address("192.168.178.240/24"))
        self.assertIsNone(bare_address("nope"))

    def test_garbage_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_prefix("not-a-prefix")


class FreeAddressesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.net = parse_prefix("192.168.178.0/24")

    def test_start_offset_one_keeps_everything(self) -> None:
        self.assertEqual(
            free_addresses_from(_avail(1, 2, 5), self.net, 1),
            ["192.168.178.1", "192.168.178.2", "192.168.178.5"],
        )

    def test_start_offset_skips_lower_addresses(self) -> None:
        self.assertEqual(
            free_addresses_from(_avail(3, 9, 10, 11), self.net, 10),
            ["192.168.178.10", "192.168.178.11"],
        )

    def test_offset_zero_includes_network_address(self) -> None:
        self.assertEqual(free_addresses_from(_avail(0, 1), self.net, 0)[0], "192.168.178.0")

    def test_ignores_malformed_and_foreign_entries(self) -> None:
        available = [
            "x",
            {"address": ""},
            {"address": "nope/24"},
            {"address": "10.0.0.5/24"},
            {"address": "2001:db8::1/64"},
            *_avail(7),
        ]
        self.assertEqual(free_addresses_from(available, self.net, 1), ["192.168.178.7"])

    def test_ipv6(self) -> None:
        net = parse_prefix("2001:db8::/64")
        available = [{"address": "2001:db8::1/64"}, {"address": "2001:db8::a/64"}]
        self.assertEqual(free_addresses_from(available, net, 5), ["2001:db8::a"])


class WindowTests(unittest.TestCase):
    def test_sum(self) -> None:
        self.assertEqual(window_size(10, 2, 3, cap=1000), 16)

    def test_capped(self) -> None:
        self.assertEqual(window_size(900, 50, 10, cap=1000), 1000)


class TakeTests(unittest.TestCase):
    def test_chunks(self) -> None:
        pool = ["a", "b", "c"]
        self.assertEqual(take(pool, 0, 2), ["a", "b"])
        self.assertEqual(take(pool, 2, 1), ["c"])

    def test_short_returns_none(self) -> None:
        self.assertIsNone(take(["a"], 0, 2))
        self.assertIsNone(take(["a"], 1, 1))


if __name__ == "__main__":
    unittest.main()
