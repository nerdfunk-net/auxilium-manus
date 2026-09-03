"""Tests for workflow_steps.common.run_param_reference.resolve_config_reference."""

from __future__ import annotations

import unittest

from workflow_steps.common.run_param_reference import resolve_config_reference


def _resolve(config: dict, run_inputs: dict | None):
    return resolve_config_reference(
        config,
        source_key="credential_source",
        param_key="credential_param",
        literal_key="credential_reference",
        run_inputs=run_inputs,
    )


class ResolveConfigReferenceTests(unittest.TestCase):
    def test_fixed_returns_literal(self) -> None:
        cfg = {"credential_source": "fixed", "credential_reference": " lab-ssh "}
        self.assertEqual(_resolve(cfg, {}), "lab-ssh")

    def test_missing_source_defaults_to_fixed(self) -> None:
        cfg = {"credential_reference": "lab-ssh"}
        self.assertEqual(_resolve(cfg, {"x": "y"}), "lab-ssh")

    def test_run_param_reads_from_run_inputs(self) -> None:
        cfg = {"credential_source": "run_param", "credential_param": "creds"}
        self.assertEqual(_resolve(cfg, {"creds": "team-a-ssh"}), "team-a-ssh")

    def test_run_param_stringifies_non_string_value(self) -> None:
        cfg = {"credential_source": "run_param", "credential_param": "inv"}
        self.assertEqual(_resolve(cfg, {"inv": 42}), "42")

    def test_run_param_blank_param_name_raises(self) -> None:
        cfg = {"credential_source": "run_param", "credential_param": "  "}
        with self.assertRaises(ValueError):
            _resolve(cfg, {"creds": "x"})

    def test_run_param_absent_from_inputs_raises(self) -> None:
        cfg = {"credential_source": "run_param", "credential_param": "creds"}
        with self.assertRaises(ValueError):
            _resolve(cfg, {"other": "x"})

    def test_run_param_none_inputs_raises(self) -> None:
        cfg = {"credential_source": "run_param", "credential_param": "creds"}
        with self.assertRaises(ValueError):
            _resolve(cfg, None)


if __name__ == "__main__":
    unittest.main()
