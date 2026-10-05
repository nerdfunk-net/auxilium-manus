"""Tests for get-device-configs effective produces and guard integration."""

from __future__ import annotations

import unittest

from models.workflow_context import Capability
from services.workflow_context.guards import StepCapabilitySpec, effective_produces


class EffectiveProducesTests(unittest.TestCase):
    def test_get_device_configs_both(self) -> None:
        spec = StepCapabilitySpec(
            step_id="get-device-configs",
            produces=frozenset({Capability.RUNNING_CONFIG, Capability.STARTUP_CONFIG}),
        )
        result = effective_produces(
            spec=spec,
            step_type="get-device-configs",
            config={"config_format": "both"},
        )
        self.assertEqual(
            result,
            frozenset({Capability.RUNNING_CONFIG, Capability.STARTUP_CONFIG}),
        )

    def test_get_device_configs_running_only(self) -> None:
        spec = StepCapabilitySpec(
            step_id="get-device-configs",
            produces=frozenset({Capability.RUNNING_CONFIG, Capability.STARTUP_CONFIG}),
        )
        result = effective_produces(
            spec=spec,
            step_type="get-device-configs",
            config={"config_format": "running"},
        )
        self.assertEqual(result, frozenset({Capability.RUNNING_CONFIG}))

    def test_other_steps_use_registry_produces(self) -> None:
        spec = StepCapabilitySpec(
            step_id="get-nautobot-devices",
            produces=frozenset({Capability.IDENTITY}),
        )
        result = effective_produces(
            spec=spec,
            step_type="get-nautobot-devices",
            config={},
        )
        self.assertEqual(result, frozenset({Capability.IDENTITY}))

    def test_update_attribute_all_regex_is_not_guaranteed(self) -> None:
        spec = StepCapabilitySpec(
            step_id="update-attribute",
            produces=frozenset({Capability.ATTRIBUTES}),
        )
        result = effective_produces(
            spec=spec,
            step_type="update-attribute",
            config={"attributes": [{"mode": "regex", "destination_path": "custom.x"}]},
        )
        self.assertEqual(result, frozenset())

    def test_update_attribute_with_one_fixed_entry_is_guaranteed(self) -> None:
        spec = StepCapabilitySpec(
            step_id="update-attribute",
            produces=frozenset({Capability.ATTRIBUTES}),
        )
        result = effective_produces(
            spec=spec,
            step_type="update-attribute",
            config={
                "attributes": [
                    {"mode": "regex", "destination_path": "custom.x"},
                    {"mode": "fixed", "destination_path": "custom.y", "fixed_value": "v"},
                ]
            },
        )
        self.assertEqual(result, frozenset({Capability.ATTRIBUTES}))

    def test_update_attribute_legacy_top_level_fixed_config(self) -> None:
        spec = StepCapabilitySpec(
            step_id="update-attribute",
            produces=frozenset({Capability.ATTRIBUTES}),
        )
        result = effective_produces(
            spec=spec,
            step_type="update-attribute",
            config={"mode": "fixed", "destination_path": "custom.x", "fixed_value": "v"},
        )
        self.assertEqual(result, frozenset({Capability.ATTRIBUTES}))

    def test_update_attribute_no_attributes_configured(self) -> None:
        spec = StepCapabilitySpec(
            step_id="update-attribute",
            produces=frozenset({Capability.ATTRIBUTES}),
        )
        result = effective_produces(
            spec=spec,
            step_type="update-attribute",
            config={"attributes": []},
        )
        self.assertEqual(result, frozenset())

    def test_run_command_never_guarantees_parsed(self) -> None:
        # The registry lists produces: [parsed], but the executor only stamps
        # Capability.PARSED when parser is "textfsm" or "genie" (and either can
        # non-fatally skip a command). The post-step guard must not require it.
        spec = StepCapabilitySpec(
            step_id="run-command",
            produces=frozenset({Capability.PARSED}),
        )
        for config in (
            {},
            {"parser": "textfsm"},
            {"parser": "genie", "pyats_source_id": "x"},
        ):
            with self.subTest(config=config):
                result = effective_produces(
                    spec=spec, step_type="run-command", config=config
                )
                self.assertEqual(result, frozenset())

    def test_catalyst_center_fact_steps_guarantee_parsed(self) -> None:
        # Every device on the success outcome has at least one fact (a device whose
        # facts all failed goes to "failure"), and run_fact_step stamps PARSED on it.
        # Downstream steps such as config-to-attributes require [parsed] and must be
        # wireable after these steps.
        for step_id in (
            "get-catalyst-center-details",
            "get-catalyst-center-topology",
            "get-catalyst-center-health",
        ):
            with self.subTest(step_id=step_id):
                spec = StepCapabilitySpec(
                    step_id=step_id, produces=frozenset({Capability.PARSED})
                )
                result = effective_produces(spec=spec, step_type=step_id, config={})
                self.assertEqual(result, frozenset({Capability.PARSED}))

    def test_run_catalyst_center_command_never_guarantees_parsed(self) -> None:
        # PARSED is only stamped with parser == "textfsm", and that is non-fatal per command.
        spec = StepCapabilitySpec(
            step_id="run-catalyst-center-command", produces=frozenset({Capability.PARSED})
        )
        result = effective_produces(
            spec=spec, step_type="run-catalyst-center-command", config={}
        )
        self.assertEqual(result, frozenset())


if __name__ == "__main__":
    unittest.main()
