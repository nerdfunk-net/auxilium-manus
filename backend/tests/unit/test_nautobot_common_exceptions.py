"""Tests for services/nautobot/common/exceptions.py."""

from __future__ import annotations

import unittest

from services.nautobot.common.exceptions import (
    NautobotAPIError,
    NautobotDuplicateResourceError,
    NautobotError,
    NautobotNotFoundError,
    NautobotResourceNotFoundError,
    handle_already_exists_error,
    is_duplicate_error,
)


class ExceptionHierarchyTests(unittest.TestCase):
    def test_not_found_is_api_error(self) -> None:
        self.assertTrue(issubclass(NautobotNotFoundError, NautobotAPIError))
        self.assertTrue(issubclass(NautobotAPIError, NautobotError))

    def test_resource_not_found_message(self) -> None:
        err = NautobotResourceNotFoundError("Device", "router1")
        self.assertEqual(err.resource_type, "Device")
        self.assertEqual(err.identifier, "router1")
        self.assertEqual(str(err), "Device not found: router1")

    def test_duplicate_resource_message(self) -> None:
        err = NautobotDuplicateResourceError("Interface", "eth0")
        self.assertEqual(str(err), "Interface already exists: eth0")


class IsDuplicateErrorTests(unittest.TestCase):
    def test_matches_known_keywords(self) -> None:
        for msg in ("already exists", "DUPLICATE key", "unique constraint failed"):
            with self.subTest(msg=msg):
                self.assertTrue(is_duplicate_error(Exception(msg)))

    def test_non_duplicate_message(self) -> None:
        self.assertFalse(is_duplicate_error(Exception("connection refused")))


class HandleAlreadyExistsErrorTests(unittest.TestCase):
    def test_returns_structured_payload(self) -> None:
        payload = handle_already_exists_error(ValueError("boom already exists"), "Device")
        self.assertEqual(payload["error"], "already_exists")
        self.assertEqual(payload["message"], "Device already exists")
        self.assertEqual(payload["detail"], "boom already exists")


if __name__ == "__main__":
    unittest.main()
