"""Tests for workflow step capability guards."""

from __future__ import annotations

import unittest

from models.workflow_context import Capability, DeviceContext, StepOutcome, WorkflowContext
from services.workflow_context.guards import StepCapabilitySpec, post_step_guard, pre_step_guard


class WorkflowContextGuardTests(unittest.TestCase):
    def test_pre_step_guard_skips_empty_inventory(self) -> None:
        spec = StepCapabilitySpec(
            step_id="parse-bgp",
            requires=frozenset({Capability.RUNNING_CONFIG}),
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        pre_step_guard(spec=spec, context=context)

    def test_pre_step_guard_missing_capability(self) -> None:
        spec = StepCapabilitySpec(
            step_id="parse-bgp",
            requires=frozenset({Capability.RUNNING_CONFIG}),
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "device-1": DeviceContext(
                    id="device-1",
                    name="device-1",
                    hostname="10.0.0.1",
                    capabilities={Capability.IDENTITY},
                )
            },
        )
        with self.assertRaises(ValueError):
            pre_step_guard(spec=spec, context=context)

    def test_pre_step_guard_missing_parsed_key(self) -> None:
        spec = StepCapabilitySpec(
            step_id="build-bgp",
            requires=frozenset({Capability.PARSED}),
            requires_parsed=frozenset({"bgp"}),
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "device-1": DeviceContext(
                    id="device-1",
                    name="device-1",
                    hostname="10.0.0.1",
                    capabilities={Capability.PARSED},
                    parsed={"vlans": [10]},
                )
            },
        )
        with self.assertRaises(ValueError):
            pre_step_guard(spec=spec, context=context)

    def test_post_step_guard_missing_produces(self) -> None:
        spec = StepCapabilitySpec(
            step_id="get-running-config",
            produces=frozenset({Capability.RUNNING_CONFIG}),
        )
        input_context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "device-1": DeviceContext(
                    id="device-1",
                    name="device-1",
                    hostname="10.0.0.1",
                    capabilities={Capability.IDENTITY},
                )
            },
        )
        success_context = input_context.model_copy(
            update={
                "devices": {
                    "device-1": input_context.devices["device-1"].model_copy(
                        update={"capabilities": {Capability.IDENTITY}}
                    )
                }
            }
        )
        outcomes = [StepOutcome(name="success", context=success_context)]
        with self.assertRaises(RuntimeError):
            post_step_guard(spec=spec, input_context=input_context, outcomes=outcomes)

    def test_post_step_guard_leaked_consumes(self) -> None:
        spec = StepCapabilitySpec(
            step_id="send-config",
            consumes=frozenset({Capability.PENDING_COMMANDS}),
        )
        input_context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "device-1": DeviceContext(
                    id="device-1",
                    name="device-1",
                    hostname="10.0.0.1",
                    capabilities={Capability.IDENTITY, Capability.PENDING_COMMANDS},
                )
            },
        )
        success_context = input_context
        outcomes = [StepOutcome(name="success", context=success_context)]
        with self.assertRaises(RuntimeError):
            post_step_guard(spec=spec, input_context=input_context, outcomes=outcomes)


if __name__ == "__main__":
    unittest.main()
