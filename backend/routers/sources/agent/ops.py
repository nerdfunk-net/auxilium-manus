"""Agent connectivity check: an encrypted ``echo`` round trip through the configured transport.

Success proves the whole path at once: the transport reaches the agent, both sides hold the same
secret and ``agent_id``, and the agent can run a handler. The nonce makes the answer fresh.
"""

from __future__ import annotations

import logging
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.rate_limit import rate_limited
from dependencies import get_agent_source_config_service
from models.agents import (
    AgentStatusResponse,
    AgentTestConnectionRequest,
    AgentTestConnectionResponse,
)
from services.agents.exceptions import (
    AgentAuthError,
    AgentCallError,
    AgentHandlerError,
    AgentOfflineError,
    AgentTimeoutError,
    AgentValidationError,
)
from services.agents.source_config_service import (
    AgentSourceConfigService,
    AgentSourceNotFoundError,
)

logger = logging.getLogger(__name__)

_ECHO_TIMEOUT_SECONDS = 10

router = APIRouter(
    prefix="/sources/agent",
    tags=["sources-agent"],
    dependencies=[Depends(require_permission("sources.agent", "read"))],
)


def _failure(message: str) -> AgentTestConnectionResponse:
    return AgentTestConnectionResponse(success=False, message=message)


def _message_for(exc: Exception, error_id: uuid.UUID) -> str:
    """A fixed, safe sentence per failure kind; the detail goes to the log under ``error_id``."""
    if isinstance(exc, AgentOfflineError):
        return f"Agent is not reachable (no heartbeat or connection refused). Ref: {error_id}"
    if isinstance(exc, AgentTimeoutError):
        return (
            "Agent did not answer in time. With the Redis transport this also happens when the "
            "secret or Agent ID differs from the agent's: it ignores messages it cannot verify. "
            f"Ref: {error_id}"
        )
    if isinstance(exc, AgentAuthError):
        return (
            "Authentication failed: check that the agent uses the same secret and agent_id as "
            f"this source. Ref: {error_id}"
        )
    if isinstance(exc, AgentHandlerError):
        return f"Agent is reachable but its echo handler failed. Ref: {error_id}"
    if isinstance(exc, AgentCallError):
        return f"Agent answered with something unusable. Ref: {error_id}"
    return f"Connection test failed. Ref: {error_id}"


@router.post(
    "/test-connection",
    response_model=AgentTestConnectionResponse,
    dependencies=[
        Depends(require_permission("sources.agent", "write")),
        Depends(rate_limited("agent-test-connection", attempts=10, window_seconds=60)),
    ],
)
async def test_connection(
    request: AgentTestConnectionRequest,
    _: User = Depends(get_current_user),
    config: AgentSourceConfigService = Depends(get_agent_source_config_service),
) -> AgentTestConnectionResponse:
    try:
        connection = config.resolve_connection(request.source_id)
    except AgentSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    nonce = secrets.token_hex(16)
    client = service_factory.build_agent_client(connection)
    started = time.monotonic()
    try:
        output = await client.invoke(
            "echo",
            {},
            {"nonce": nonce},
            timeout=min(_ECHO_TIMEOUT_SECONDS, connection.max_timeout_seconds),
        )
    except Exception as exc:
        error_id = uuid.uuid4()
        logger.warning(
            "agent test-connection failed source=%s error_id=%s kind=%s",
            request.source_id,
            error_id,
            type(exc).__name__,
            exc_info=not isinstance(exc, AgentCallError),
        )
        return _failure(_message_for(exc, error_id))
    finally:
        await client.aclose()

    latency_ms = int((time.monotonic() - started) * 1000)
    if output.get("nonce") != nonce:
        return _failure("Agent answered, but its echo did not return the expected value.")
    return AgentTestConnectionResponse(
        success=True, message="Agent is reachable and authenticated.", latency_ms=latency_ms
    )


@router.get("/{source_id}/status", response_model=AgentStatusResponse)
async def agent_status(
    source_id: str,
    _: User = Depends(get_current_user),
    config: AgentSourceConfigService = Depends(get_agent_source_config_service),
) -> AgentStatusResponse:
    """Heartbeat view (Redis agents): online, version and the handlers the agent offers."""
    try:
        connection = config.resolve_connection(source_id)
    except AgentSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    view = await service_factory.read_agent_status(connection)
    return AgentStatusResponse(
        transport=connection.transport,
        online=view.online,
        version=view.version,
        handlers=view.handlers,
        last_heartbeat=view.last_heartbeat,
        message=view.message,
    )
