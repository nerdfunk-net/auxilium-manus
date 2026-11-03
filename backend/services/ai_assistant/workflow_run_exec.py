"""Starts the workflow run the user confirmed (doc/AI_TOOL_CHAIN.md §16).

Called only from ``POST /ai/exec/workflow-run`` after the user's click. The workflow, inputs and
devices come from the signed token, never from the request, and the run is started as the
confirming user through ``RunService.trigger_ai_run``, which checks again that the workflow is
still released and visible and validates the inputs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from services.ai_assistant.released_workflow_reader import ReleasedWorkflowReader
from services.ai_assistant.workflow_run_token import verify_run_token

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartedRun:
    run_id: int
    workflow_id: int


class WorkflowRunExecutor:
    def __init__(self, reader: ReleasedWorkflowReader) -> None:
        self._reader = reader

    async def execute(self, *, user_id: int, token: str) -> StartedRun:
        """Raises ``InvalidRunTokenError`` for a bad token; domain errors pass through."""
        grant = verify_run_token(token, user_id=user_id)
        run_id = await self._reader.start(
            grant.workflow_id, run_inputs=dict(grant.run_inputs), device_ids=list(grant.device_ids)
        )
        # Ids and input names only: values may be sensitive.
        logger.info(
            "AI assistant started workflow run run_id=%s workflow_id=%s user_id=%s inputs=%s",
            run_id,
            grant.workflow_id,
            user_id,
            sorted(grant.run_inputs),
        )
        return StartedRun(run_id=run_id, workflow_id=grant.workflow_id)
