"""Executor for the batfish-interface-properties step.

Wraps Batfish's `interfaceProperties` question against the snapshot an upstream
batfish-init-snapshot step initialized. Everything (config parse, query, artifact and metadata
storage, the route_empty_to_devices / empty_match_mode audit filter, per-device enrichment) is
``common.batfish_properties.run_property_step``; this module names the spec and the query.

Not the same question as batfish-node-properties: `interfaceProperties` returns one row per
(node, interface) pair keyed by a nested `Interface` column (doc/BATFISH_INTEGRATION.md "Batfish
Interface Properties"); the spec nests each device's fields under `Interfaces`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.interface_properties_spec import INTERFACE_PROPERTIES_SPEC
from services.batfish.query_helpers import query_interface_properties
from workflow_steps.batfish_interface_properties.config import get_config
from workflow_steps.common.batfish_properties import run_property_step

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

_STEP_ID = "batfish-interface-properties"


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions  # unused: Batfish is reached via pybatfish, not Netmiko

    return await run_property_step(
        step_id=_STEP_ID,
        spec=INTERFACE_PROPERTIES_SPEC,
        query=query_interface_properties,
        extra_filters=("interfaces",),
        default_output_key="batfish_interface_properties",
        default_config=get_config(),
        config=config,
        context=context,
        run=run,
        artifact_service=artifact_service,
        node_id=node_id,
    )
