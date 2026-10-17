"""Tests for services/workflow/workflow_service.py::_validate_static_attributes.

Regression coverage for a real bug found via live testing (see
doc/ai_collaboration/PROCESS.md): the type-check had no branch for
type == "reference" at all, so ANY non-null default on a reference-type
static attribute was unconditionally rejected — making it impossible to save
the run_param + defaulted-reference pattern AI_VOCABULARY.md recommends for
targeting a named inventory.
"""

from __future__ import annotations

import unittest

from core.domain_exceptions import ValidationFailedError
from services.workflow.workflow_service import _validate_static_attributes


class ValidateStaticAttributesTests(unittest.TestCase):
    def test_reference_inventory_default_int_is_valid(self) -> None:
        _validate_static_attributes(
            [
                {
                    "name": "target_inventory",
                    "type": "reference",
                    "ref_kind": "inventory",
                    "default": 1,
                    "required": False,
                }
            ]
        )  # must not raise

    def test_reference_credential_default_str_is_valid(self) -> None:
        _validate_static_attributes(
            [
                {
                    "name": "ssh_credential",
                    "type": "reference",
                    "ref_kind": "credential",
                    "default": "cisco - noc",
                    "required": False,
                }
            ]
        )  # must not raise

    def test_reference_inventory_default_must_be_int_not_str(self) -> None:
        with self.assertRaises(ValidationFailedError):
            _validate_static_attributes(
                [
                    {
                        "name": "target_inventory",
                        "type": "reference",
                        "ref_kind": "inventory",
                        "default": "LAB",
                        "required": False,
                    }
                ]
            )

    def test_reference_credential_default_must_be_str_not_int(self) -> None:
        with self.assertRaises(ValidationFailedError):
            _validate_static_attributes(
                [
                    {
                        "name": "ssh_credential",
                        "type": "reference",
                        "ref_kind": "credential",
                        "default": 1,
                        "required": False,
                    }
                ]
            )

    def test_reference_inventory_default_bool_is_rejected(self) -> None:
        # bool is a subclass of int in Python; must not slip through as a
        # valid inventory id.
        with self.assertRaises(ValidationFailedError):
            _validate_static_attributes(
                [
                    {
                        "name": "target_inventory",
                        "type": "reference",
                        "ref_kind": "inventory",
                        "default": True,
                        "required": False,
                    }
                ]
            )

    def test_no_default_is_always_valid(self) -> None:
        _validate_static_attributes(
            [
                {
                    "name": "target_inventory",
                    "type": "reference",
                    "ref_kind": "inventory",
                    "required": False,
                }
            ]
        )  # must not raise

    def test_scalar_types_still_validated_correctly(self) -> None:
        _validate_static_attributes(
            [
                {"name": "vlan_id", "type": "number", "default": 100},
                {"name": "note", "type": "string", "default": "n/a"},
                {"name": "confirm", "type": "boolean", "default": False},
            ]
        )  # must not raise
        with self.assertRaises(ValidationFailedError):
            _validate_static_attributes([{"name": "vlan_id", "type": "number", "default": "100"}])


if __name__ == "__main__":
    unittest.main()
