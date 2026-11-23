"""The failure record of one failed agent call: ``(code, message, FailureInfo)``.

Shared by ``route-to-agent`` (one record per device) and ``get-from-agent`` (one record for the
step). Free text is kept only where it is safe: the agent errors write their own messages
(never secrets or payload content); anything else is reduced to its class name.
"""

from __future__ import annotations

from models.failure import FailureInfo
from services.agents.exceptions import (
    AgentAuthError,
    AgentCallError,
    AgentHandlerError,
    AgentOfflineError,
    AgentPayloadTooLargeError,
    AgentTimeoutError,
    AgentTransportError,
    AgentValidationError,
)

_CODES: tuple[tuple[type[AgentCallError], str], ...] = (
    (AgentOfflineError, "agent_offline"),
    (AgentTimeoutError, "agent_timeout"),
    (AgentAuthError, "agent_auth_failed"),
    (AgentTransportError, "agent_transport_error"),
    (AgentPayloadTooLargeError, "payload_too_large"),
    (AgentHandlerError, "agent_handler_error"),
)


def describe_call_failure(exc: Exception) -> tuple[str, str, FailureInfo]:
    """``(code, message, FailureInfo)`` for a failed call."""
    for error_type, code in _CODES:
        if isinstance(exc, error_type):
            return code, str(exc), exc.failure
    if isinstance(exc, AgentValidationError):
        return (
            "agent_request_invalid",
            str(exc),
            FailureInfo(phase="agent", kind="bad_request", exception_type=type(exc).__name__),
        )
    # Anything else is a bug on our side; its text can carry anything, so only the class name.
    return (
        "internal_error",
        type(exc).__name__,
        FailureInfo(phase="internal", kind="internal_error", exception_type=type(exc).__name__),
    )
