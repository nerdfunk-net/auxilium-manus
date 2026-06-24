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


if __name__ == "__main__":
    unittest.main()
