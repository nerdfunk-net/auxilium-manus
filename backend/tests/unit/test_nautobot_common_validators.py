"""Table-driven tests for services/nautobot/common/validators.py (pure functions)."""

from __future__ import annotations

import unittest

from services.nautobot.common.validators import (
    is_valid_uuid,
    validate_cidr,
    validate_ip_address,
    validate_mac_address,
    validate_required_fields,
)

_UUID = "550e8400-e29b-41d4-a716-446655440000"


class IsValidUuidTests(unittest.TestCase):
    def test_accepts_lowercase_and_uppercase(self) -> None:
        self.assertTrue(is_valid_uuid(_UUID))
        self.assertTrue(is_valid_uuid(_UUID.upper()))

    def test_rejects_non_uuid_strings(self) -> None:
        for value in ("not-a-uuid", "", "550e8400-e29b-41d4-a716", f"{_UUID}-extra", "1234"):
            with self.subTest(value=value):
                self.assertFalse(is_valid_uuid(value))


class ValidateIpAddressTests(unittest.TestCase):
    def test_valid_addresses(self) -> None:
        for value in ("192.168.1.1", "192.168.1.1/24", "10.0.0.0/8", "2001:db8::1", "fe80::1/64"):
            with self.subTest(value=value):
                self.assertTrue(validate_ip_address(value))

    def test_invalid_addresses(self) -> None:
        for value in ("invalid", "", "hello.world", "192-168-1-1"):
            with self.subTest(value=value):
                self.assertFalse(validate_ip_address(value))


class ValidateMacAddressTests(unittest.TestCase):
    def test_valid_macs(self) -> None:
        for value in ("00:1A:2B:3C:4D:5E", "00-1a-2b-3c-4d-5e", "aa:bb:cc:dd:ee:ff"):
            with self.subTest(value=value):
                self.assertTrue(validate_mac_address(value))

    def test_invalid_macs(self) -> None:
        for value in ("invalid", "00:1A:2B:3C:4D", "001A.2B3C.4D5E", ""):
            with self.subTest(value=value):
                self.assertFalse(validate_mac_address(value))


class ValidateCidrTests(unittest.TestCase):
    def test_requires_slash(self) -> None:
        self.assertFalse(validate_cidr("192.168.1.1"))

    def test_valid_cidr(self) -> None:
        self.assertTrue(validate_cidr("192.168.1.0/24"))

    def test_slash_but_bad_ip(self) -> None:
        self.assertFalse(validate_cidr("not-an-ip/24"))


class ValidateRequiredFieldsTests(unittest.TestCase):
    def test_passes_when_all_present(self) -> None:
        validate_required_fields({"name": "x", "status": "active"}, ["name", "status"])

    def test_raises_for_missing_key(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_required_fields({"name": "x"}, ["name", "status"])
        self.assertIn("status", str(ctx.exception))

    def test_raises_for_empty_value(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_required_fields({"name": "", "status": None}, ["name", "status"])
        self.assertIn("name", str(ctx.exception))
        self.assertIn("status", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
