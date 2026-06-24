"""Runtime capability guards for workflow step execution."""

from __future__ import annotations

from dataclasses import dataclass, field

from models.workflow_context import Capability, StepOutcome, WorkflowContext


@dataclass(frozen=True)
class StepCapabilitySpec:
    """Declared capability contract for a workflow step (from registry)."""

    step_id: str
    requires: frozenset[Capability] = field(default_factory=frozenset)
    produces: frozenset[Capability] = field(default_factory=frozenset)
    consumes: frozenset[Capability] = field(default_factory=frozenset)
    requires_parsed: frozenset[str] = field(default_factory=frozenset)


def pre_step_guard(*, spec: StepCapabilitySpec, context: WorkflowContext) -> None:
    """Validate required capabilities and parser keys before a step runs."""
    if not context.devices:
        return

    missing_capabilities = set(spec.requires) - context.provided_capabilities()
    if missing_capabilities:
        raise ValueError(
            f"Step {spec.step_id}: missing required capabilities {missing_capabilities}"
        )

    missing_parsed_keys = set(spec.requires_parsed) - context.provided_parsed_keys()
    if missing_parsed_keys:
        raise ValueError(
            f"Step {spec.step_id}: missing required parsed keys {missing_parsed_keys}"
        )


def post_step_guard(
    *,
    spec: StepCapabilitySpec,
    input_context: WorkflowContext,
    outcomes: list[StepOutcome],
) -> None:
    """Validate the success outcome after a step returns."""
    success_outcome = next((outcome for outcome in outcomes if outcome.name == "success"), None)
    if success_outcome is None:
        return

    touched = set(success_outcome.context.devices) & set(input_context.devices)
    for device_id in touched:
        device = success_outcome.context.devices[device_id]

        missing_produces = set(spec.produces) - device.capabilities
        if missing_produces:
            raise RuntimeError(
                f"Step {spec.step_id} declared produces={set(spec.produces)} but device "
                f"{device_id} is missing {missing_produces} on the success path"
            )

        leaked_consumes = set(spec.consumes) & device.capabilities
        if leaked_consumes:
            raise RuntimeError(
                f"Step {spec.step_id} declared consumes={set(spec.consumes)} but device "
                f"{device_id} still has {leaked_consumes} on the success path"
            )
