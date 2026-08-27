"""Resolve which Hatchet workflow object a WorkflowRun dispatches into.

Unpublished workflows (the overwhelming common case) dispatch into the single
shared WorkflowExecution workflow exactly as today — one cheap indexed lookup
by workflow_id, no behavior change. Published ("background tier") workflows
dispatch into their own dedicated Hatchet workflow name, registered by the
second worker process (hatchet/dynamic_worker.py); this module never imports
dynamic_worker.py — it just builds a lightweight client-side Workflow handle
for the name, which is all `.run_no_wait()` needs. Triggering a run is a pure
client -> engine call keyed by workflow name; it does not require the calling
process to itself be a registered worker for that name (RunService.trigger_run
already proves this today, calling workflow_execution.run_no_wait(...) from
the FastAPI process, which is never a registered worker).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from hatchet.client import hatchet
from hatchet.workflows.workflow_run import WorkflowRunInput
from hatchet.workflows.workflow_run import workflow as workflow_execution

if TYPE_CHECKING:
    from hatchet_sdk.runnables.workflow import Workflow as HatchetWorkflow

    from core.models.workflows import Workflow

# Process-local memo of dispatch-only handles for published workflows — these
# are lightweight client objects (no task attached), never registered as a
# worker action set, so memoizing them just avoids reconstructing one per call.
_dispatch_handle_cache: dict[str, HatchetWorkflow[WorkflowRunInput]] = {}


def _dispatch_handle(name: str) -> HatchetWorkflow[WorkflowRunInput]:
    handle = _dispatch_handle_cache.get(name)
    if handle is None:
        handle = hatchet.workflow(name=name, input_validator=WorkflowRunInput)
        _dispatch_handle_cache[name] = handle
    return handle


def resolve_dispatch_workflow(
    workflow: Workflow, db: Session
) -> HatchetWorkflow[WorkflowRunInput]:
    """Return the Hatchet Workflow object trigger_run/dispatch should call
    .run_no_wait(WorkflowRunInput(run_id=...)) on for this Workflow row."""
    from repositories.background_tier_repository import BackgroundTierRepository

    tier = BackgroundTierRepository(db).get_by_workflow_id(workflow.id)
    if tier is None:
        return workflow_execution
    return _dispatch_handle(tier.hatchet_workflow_name)
