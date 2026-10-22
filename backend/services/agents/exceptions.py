"""Domain errors of the agent integration.

``AgentValidationError`` is a ``ValueError`` so workflow-step executors can let a configuration
problem propagate per the step contract (ValueError = configuration problem).

``AgentCallError`` and its subclasses are *per-call* failures (one device): each carries a
``kind`` from the closed ``models.failure.FailureKind`` vocabulary so the step can record why a
device failed without copying message text. Messages never contain secrets or payload content.
"""

from __future__ import annotations

from typing import ClassVar


class AgentValidationError(ValueError):
    """An agent source or request is misconfigured (never carries secret material)."""


class AgentCallError(RuntimeError):
    """One call to an agent failed."""

    kind: ClassVar[str] = "unknown"


class AgentOfflineError(AgentCallError):
    """The agent is not reachable (connection refused, or no heartbeat on Redis)."""

    kind = "agent_offline"


class AgentTimeoutError(AgentCallError):
    """The agent did not answer within the timeout."""

    kind = "timeout"


class AgentTransportError(AgentCallError):
    """The transport delivered something unusable (HTTP error status, garbage, too large)."""

    kind = "invalid_response"


class AgentAuthError(AgentCallError):
    """The agent rejected our token, or its answer failed authentication (wrong secret,
    tampered, replayed, expired)."""

    kind = "auth_failed"


class AgentPayloadTooLargeError(AgentCallError):
    """The request exceeds the agent's ``max_request_bytes``."""

    kind = "payload_too_large"


class AgentHandlerError(AgentCallError):
    """The agent ran the handler and it reported an error."""

    kind = "agent_handler_error"

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(f"{error_type}: {message}" if message else error_type)
        self.error_type = error_type
