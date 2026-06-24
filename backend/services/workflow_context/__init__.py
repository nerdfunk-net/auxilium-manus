"""WorkflowContext merge and runtime guards."""

from services.workflow_context.guards import StepCapabilitySpec, post_step_guard, pre_step_guard
from services.workflow_context.merge import (
    flatten_pending_commands,
    merge_device_contexts,
    merge_workflow_contexts,
)
from services.workflow_context.registry import capability_spec_from_plugin

__all__ = [
    "StepCapabilitySpec",
    "capability_spec_from_plugin",
    "flatten_pending_commands",
    "merge_device_contexts",
    "merge_workflow_contexts",
    "post_step_guard",
    "pre_step_guard",
]
