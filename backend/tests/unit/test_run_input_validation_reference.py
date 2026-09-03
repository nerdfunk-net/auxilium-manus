"""Reference-typed static attributes in resolve_run_inputs (shape only)."""

from __future__ import annotations

import unittest

from services.execution.run_input_validation import (
    RunInputValidationError,
    resolve_run_inputs,
)

_INV = {"name": "inv", "type": "reference", "ref_kind": "inventory", "required": True}
_CRED = {"name": "cred", "type": "reference", "ref_kind": "credential", "required": True}


class ReferenceCoercionTests(unittest.TestCase):
    def test_inventory_accepts_int(self) -> None:
        self.assertEqual(resolve_run_inputs([_INV], {"inv": 7})["inv"], 7)

    def test_inventory_coerces_int_like_string(self) -> None:
        self.assertEqual(resolve_run_inputs([_INV], {"inv": "7"})["inv"], 7)

    def test_inventory_rejects_non_numeric(self) -> None:
        with self.assertRaises(RunInputValidationError):
            resolve_run_inputs([_INV], {"inv": "core-routers"})

    def test_inventory_rejects_zero_and_negative(self) -> None:
        with self.assertRaises(RunInputValidationError):
            resolve_run_inputs([_INV], {"inv": 0})
        with self.assertRaises(RunInputValidationError):
            resolve_run_inputs([_INV], {"inv": -3})

    def test_inventory_rejects_bool(self) -> None:
        with self.assertRaises(RunInputValidationError):
            resolve_run_inputs([_INV], {"inv": True})

    def test_credential_accepts_non_empty_string(self) -> None:
        self.assertEqual(
            resolve_run_inputs([_CRED], {"cred": " team-ssh "})["cred"], "team-ssh"
        )

    def test_credential_rejects_empty(self) -> None:
        with self.assertRaises(RunInputValidationError):
            resolve_run_inputs([_CRED], {"cred": "   "})

    def test_credential_rejects_non_string(self) -> None:
        with self.assertRaises(RunInputValidationError):
            resolve_run_inputs([_CRED], {"cred": 5})

    def test_required_reference_without_value_or_default_fails(self) -> None:
        with self.assertRaises(RunInputValidationError):
            resolve_run_inputs([_INV], {})


if __name__ == "__main__":
    unittest.main()
