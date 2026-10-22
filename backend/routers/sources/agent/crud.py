"""CRUD for configured agent sources (transport, identity, shared-secret credential)."""

from __future__ import annotations

from dependencies import get_agent_source_config_service
from models.agents import (
    AgentSourceCreateRequest,
    AgentSourceListResponse,
    AgentSourceResponse,
    AgentSourceUpdateRequest,
)
from routers.source_crud_factory import build_source_crud_router
from services.agents.exceptions import AgentValidationError
from services.agents.source_config_service import (
    AgentSourceConflictError,
    AgentSourceNotFoundError,
)

router = build_source_crud_router(
    source_type="agent",
    display_name="Agent",
    permission_resource="sources.agent",
    tag="sources-agent",
    service_dependency=get_agent_source_config_service,
    create_model=AgentSourceCreateRequest,
    update_model=AgentSourceUpdateRequest,
    response_model=AgentSourceResponse,
    list_response_model=AgentSourceListResponse,
    not_found_error=AgentSourceNotFoundError,
    conflict_error=AgentSourceConflictError,
    validation_errors=(AgentValidationError,),
    create_kwargs=lambda r: r.model_dump(),
    update_kwargs=lambda r: r.model_dump(),
)
