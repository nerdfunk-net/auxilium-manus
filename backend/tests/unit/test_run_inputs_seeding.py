"""Tests for seeding WorkflowRun.run_inputs into device attribute_bags.

See doc/WORKFLOW-STEPS.md "Static attributes" — values supplied at trigger
time must reach every device's attribute_bags["run_input"] so existing
{bag.field} resolution (Jinja, route-on-attribute, update-attribute) can
read them without any step-specific wiring.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.execution.step_runner import StepRunner
from services.workflow_context.run_inputs import RUN_INPUT_BAG_NAME, seed_run_input_bag


def _device(device_id: str, **bags: dict) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        attribute_bags=bags,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


class SeedRunInputBagTests(unittest.TestCase):
    def test_stamps_bag_on_every_device(self) -> None:
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"a": _device("a"), "b": _device("b")},
        )

        result = seed_run_input_bag(context, {"vlan_id": 100})

        self.assertEqual(result.devices["a"].attribute_bags[RUN_INPUT_BAG_NAME], {"vlan_id": 100})
        self.assertEqual(result.devices["b"].attribute_bags[RUN_INPUT_BAG_NAME], {"vlan_id": 100})

    def test_noop_when_run_inputs_empty(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"a": _device("a")})

        result = seed_run_input_bag(context, {})

        self.assertIs(result, context)

    def test_idempotent_when_bag_already_present(self) -> None:
        device = _device("a", run_input={"vlan_id": 999})
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"a": device})

        result = seed_run_input_bag(context, {"vlan_id": 100})

        self.assertIs(result, context)
        self.assertEqual(result.devices["a"].attribute_bags["run_input"], {"vlan_id": 999})

    def test_does_not_mutate_original_context(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"a": _device("a")})

        seed_run_input_bag(context, {"vlan_id": 100})

        self.assertNotIn(RUN_INPUT_BAG_NAME, context.devices["a"].attribute_bags)


class StepRunnerSeedRunInputsTests(unittest.TestCase):
    def test_seeds_bag_into_every_outcome_context(self) -> None:
        run = MagicMock(run_inputs={"vlan_id": 100})
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"a": _device("a")})
        outcomes = [StepOutcome(name="success", context=context)]

        seeded = StepRunner._seed_run_inputs(run, outcomes)

        self.assertEqual(
            seeded[0].context.devices["a"].attribute_bags[RUN_INPUT_BAG_NAME], {"vlan_id": 100}
        )
        self.assertEqual(seeded[0].name, "success")

    def test_noop_when_run_has_no_run_inputs(self) -> None:
        run = MagicMock(run_inputs=None)
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"a": _device("a")})
        outcomes = [StepOutcome(name="success", context=context)]

        seeded = StepRunner._seed_run_inputs(run, outcomes)

        self.assertIs(seeded, outcomes)


if __name__ == "__main__":
    unittest.main()
