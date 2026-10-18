"""Hatchet ``additional_metadata`` for the runs we trigger.

Hatchet names a run ``<workflow name>-<timestamp>`` and the SDK offers no per-run display name,
so ``additional_metadata`` is what makes a run findable in the Hatchet dashboard (shown on the run
and filterable). Values must be strings.
"""

from __future__ import annotations

from hatchet_sdk.types.trigger import TriggerWorkflowOptions


def run_trigger_options(
    *,
    run_id: int,
    workflow_name: str | None,
    trigger_type: str,
    parent_run_id: int | None = None,
) -> TriggerWorkflowOptions:
    """Options for dispatching one ``WorkflowRun`` into the engine."""
    metadata = {"run_id": str(run_id), "trigger_type": trigger_type}
    if workflow_name:
        metadata["workflow_name"] = workflow_name
    if parent_run_id is not None:
        metadata["parent_run_id"] = str(parent_run_id)
    return TriggerWorkflowOptions(additional_metadata=metadata)


def device_group_trigger_options(*, parent_run_id: int, child_index: int) -> TriggerWorkflowOptions:
    """Options for one fan-out child (``DeviceGroupExecution``) of ``parent_run_id``."""
    return TriggerWorkflowOptions(
        additional_metadata={
            "run_id": str(parent_run_id),
            "parent_run_id": str(parent_run_id),
            "child_index": str(child_index),
            "trigger_type": "fan_out",
        }
    )
