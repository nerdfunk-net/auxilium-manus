"""Executor for the stop-here (inspection breakpoint) step.

Truncates the run at this point on the canvas: ``StepRunner.load_execution_graph``
already drops every node downstream of a ``stop-here`` node before the walk
starts (see ``services/execution/step_runner/graph_resolution.py::resolve_stop_here``),
so by the time this executor runs there is nothing left to hand off to — it
only needs to forward the input context unchanged so its own
``WorkflowStepResult`` shows exactly what reached this point in the graph.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del config, artifact_service, device_sessions  # unused — pure inspection point

    logger.info(
        "stop-here reached run_id=%s node_id=%s devices=%d",
        run.id,
        node_id,
        len(context.devices),
    )
    return [StepOutcome(name="success", context=context)]
