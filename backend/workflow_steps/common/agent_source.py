"""Agent source resolution for workflow steps.

Goes through the shared ``source_credentials.resolve_source`` like every other source: every
configuration problem (unknown source, missing credential, secret below the policy) becomes a
``ValueError`` with the step id in front, so the step contract's "ValueError = configuration
error" holds - see doc/WORKFLOW-STEPS.md.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from services.agents.exceptions import AgentValidationError
from services.agents.source_config_service import AgentConnection, AgentSourceConfigService
from workflow_steps.common.source_credentials import resolve_source


def resolve_agent_connection(db: Session, source_id: str, *, step_id: str) -> AgentConnection:
    normalized = (source_id or "").strip()
    if not normalized:
        raise ValueError(f"{step_id}: agent_source_id is not configured")
    service = AgentSourceConfigService(db)
    return resolve_source(
        service,
        normalized,
        step_id=step_id,
        invalid=AgentValidationError,
        resolve=service.resolve_connection,
    )
