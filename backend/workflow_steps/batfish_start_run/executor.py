"""Executor for the batfish-start-run step.

Exists solely so a git-mode Init Batfish Snapshot step (which reads configs
from a Git repository and needs no live devices at all -- see
doc/BATFISH_INTEGRATION.md "Config source: live vs. git") can still be wired
into on the canvas: batfish-init-snapshot declares requires: [identity]
(unchanged, so live-mode workflows keep their existing device-selection ->
Init wiring), and the canvas's own connection-validity rule
(workflow-canvas.tsx::isValidConnection) requires some upstream node that
produces: [identity] before it will accept an edge into a requires:
[identity] step, regardless of what that upstream step's device output
actually contains.

Explicitly clears context.devices (rather than passing through whatever
came before unchanged) so the step's contract is unambiguous: after this
step, there are no devices, regardless of what preceded it on the canvas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del config, run, artifact_service, node_id, device_sessions  # unused: pure seed step

    new_context = context.model_copy(update={"devices": {}})
    return [StepOutcome(name="success", context=new_context)]
