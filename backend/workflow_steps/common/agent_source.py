"""Agent source resolution for workflow steps.

Mirrors ``workflow_steps.common.nautobot_source``: every configuration problem (unknown source,
missing credential, secret below the policy) becomes a ``ValueError`` so the step contract's
"ValueError = configuration error" holds - see doc/WORKFLOW-STEPS.md.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from services.agents.source_config_service import (
    AgentConnection,
    AgentSourceConfigService,
    AgentSourceNotFoundError,
)


def resolve_agent_connection(db: Session, source_id: str, *, step_id: str) -> AgentConnection:
    normalized = (source_id or "").strip()
    if not normalized:
        raise ValueError(f"{step_id}: agent_source_id is not configured")
    try:
        return AgentSourceConfigService(db).resolve_connection(normalized)
    except AgentSourceNotFoundError as exc:
        raise ValueError(f"{step_id}: {exc}") from exc
