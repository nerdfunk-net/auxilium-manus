"""Seed WorkflowRun.run_inputs onto every device's attribute_bags.

Static attributes are a workflow-level concept (declared in the properties
panel, not a canvas step), so there is no inventory-step executor to seed
them from. Instead this is hooked directly into StepRunner right after any
step outcome that carries devices — see doc/WORKFLOW-STEPS.md "Static
attributes" for the full contract.
"""

from __future__ import annotations

from typing import Any

from models.workflow_context import DeviceContext, WorkflowContext

RUN_INPUT_BAG_NAME = "run_input"


def seed_run_input_bag(context: WorkflowContext, run_inputs: dict[str, Any]) -> WorkflowContext:
    """Idempotently stamp ``run_inputs`` onto every device that doesn't
    already carry a "run_input" bag.

    No-op (returns ``context`` unchanged) when ``run_inputs`` is empty or
    every device already has the bag — avoids needless ``model_copy`` churn
    on every step of a run with no static attributes declared, which is the
    common case.
    """
    if not run_inputs:
        return context

    updated: dict[str, DeviceContext] = {}
    changed = False
    for device_id, device in context.devices.items():
        if RUN_INPUT_BAG_NAME in device.attribute_bags:
            updated[device_id] = device
            continue
        changed = True
        updated[device_id] = device.model_copy(
            update={
                "attribute_bags": {
                    **device.attribute_bags,
                    RUN_INPUT_BAG_NAME: dict(run_inputs),
                }
            }
        )

    if not changed:
        return context
    return context.model_copy(update={"devices": updated})
