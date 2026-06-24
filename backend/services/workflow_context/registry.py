"""Map plugin registry entries to runtime capability specs."""

from __future__ import annotations

from models.plugins import PluginDefinition
from models.workflow_context import Capability
from services.workflow_context.guards import StepCapabilitySpec


def capability_spec_from_plugin(plugin: PluginDefinition) -> StepCapabilitySpec:
    return StepCapabilitySpec(
        step_id=plugin.id,
        requires=frozenset(Capability(value) for value in plugin.requires),
        produces=frozenset(Capability(value) for value in plugin.produces),
        consumes=frozenset(Capability(value) for value in plugin.consumes),
        requires_parsed=frozenset(plugin.requires_parsed),
    )
