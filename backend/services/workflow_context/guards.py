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


_LEGACY_ATTRIBUTE_KEYS = (
    "mode",
    "destination_path",
    "fixed_value",
    "source_path",
    "pattern",
    "destination_template",
    "regex_flags",
)


def _update_attribute_has_guaranteed_write(config: dict) -> bool:
    """True if update-attribute is guaranteed to write on every device.

    A ``fixed`` mode entry always writes (its ``fixed_value`` is validated once,
    up front, for all devices). A ``regex`` mode entry only writes when its
    pattern matches that device's resolved source value, so it can legitimately
    skip a device — meaning ``Capability.ATTRIBUTES`` cannot be promised unless
    at least one configured entry is in ``fixed`` mode.
    """
    raw_attributes = config.get("attributes")
    if isinstance(raw_attributes, list):
        entries = raw_attributes
    elif any(key in config for key in _LEGACY_ATTRIBUTE_KEYS):
        entries = [config]
    else:
        entries = []
    return any(
        isinstance(entry, dict) and str(entry.get("mode", "fixed")).strip().lower() == "fixed"
        for entry in entries
    )


def effective_produces(
    *,
    spec: StepCapabilitySpec,
    step_type: str,
    config: dict,
) -> frozenset[Capability]:
    """Return capabilities a step must add on the success path for this config."""
    if step_type == "get-device-configs":
        config_format = str(config.get("config_format") or "both").strip().lower()
        if config_format == "running":
            return frozenset({Capability.RUNNING_CONFIG})
        if config_format == "startup":
            return frozenset({Capability.STARTUP_CONFIG})
        return frozenset({Capability.RUNNING_CONFIG, Capability.STARTUP_CONFIG})
    if step_type == "render-jinja-template":
        return frozenset({Capability.PARSED})
    if step_type == "update-attribute":
        if _update_attribute_has_guaranteed_write(config):
            return frozenset({Capability.ATTRIBUTES})
        return frozenset()
    return spec.produces


def post_step_guard(
    *,
    spec: StepCapabilitySpec,
    input_context: WorkflowContext,
    outcomes: list[StepOutcome],
    expected_produces: frozenset[Capability] | None = None,
) -> None:
    """Validate the success outcome after a step returns."""
    produces = expected_produces if expected_produces is not None else spec.produces
    success_outcome = next((outcome for outcome in outcomes if outcome.name == "success"), None)
    if success_outcome is None:
        return

    touched = set(success_outcome.context.devices) & set(input_context.devices)
    for device_id in touched:
        device = success_outcome.context.devices[device_id]

        missing_produces = set(produces) - device.capabilities
        if missing_produces:
            raise RuntimeError(
                f"Step {spec.step_id} expected produces={set(produces)} but device "
                f"{device_id} is missing {missing_produces} on the success path"
            )

        leaked_consumes = set(spec.consumes) & device.capabilities
        if leaked_consumes:
            raise RuntimeError(
                f"Step {spec.step_id} declared consumes={set(spec.consumes)} but device "
                f"{device_id} still has {leaked_consumes} on the success path"
            )
