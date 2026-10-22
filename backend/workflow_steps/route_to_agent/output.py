"""The contract for what an agent may return, and the failure records for a call that broke it."""

from __future__ import annotations

import json
from typing import Any

from core.config import settings
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
from workflow_steps.route_to_agent.request import OUTPUT_KEY_PATTERN

MAX_VALUE_DEPTH = 8


class OutputRejectedError(Exception):
    """The agent's answer broke the step's output contract (never echoes the values)."""


def _too_deep(value: Any) -> bool:
    """True when containers are nested more than MAX_VALUE_DEPTH levels (iterative: a payload
    nested thousands of levels deep must not exhaust the interpreter's recursion limit)."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, level = stack.pop()
        if isinstance(current, dict):
            children: Any = current.values()
        elif isinstance(current, list):
            children = current
        else:
            continue
        if level + 1 > MAX_VALUE_DEPTH:
            return True
        stack.extend((child, level + 1) for child in children)
    return False


def check_output(
    output: dict[str, Any], *, output_keys: tuple[str, ...], allow_missing: bool
) -> dict[str, Any]:
    """Return *output* if it only holds declared, plainly named, bounded JSON values."""
    for key in output:
        if not isinstance(key, str) or not OUTPUT_KEY_PATTERN.fullmatch(key):
            raise OutputRejectedError("the agent returned a key that is not a plain name")
    undeclared = sorted(set(output) - set(output_keys))
    if undeclared:
        raise OutputRejectedError(f"the agent returned undeclared keys: {', '.join(undeclared)}")
    missing = [key for key in output_keys if key not in output]
    if missing and not allow_missing:
        raise OutputRejectedError(f"the agent did not return: {', '.join(missing)}")

    total = 0
    for key, value in output.items():
        if _too_deep(value):
            raise OutputRejectedError(f"value of {key!r} is nested too deeply")
        size = len(json.dumps(value, separators=(",", ":")).encode("utf-8"))
        if size > settings.step_output_value_max_bytes:
            raise OutputRejectedError(
                f"value of {key!r} is {size} bytes, above the limit of "
                f"{settings.step_output_value_max_bytes}"
            )
        total += size
    if total > settings.step_output_max_bytes:
        raise OutputRejectedError("the agent's answer is above the total output limit")
    return output


_CODES: tuple[tuple[type[Exception], str, bool], ...] = (
    (AgentOfflineError, "agent_offline", True),
    (AgentTimeoutError, "agent_timeout", True),
    (AgentAuthError, "agent_auth_failed", False),
    (AgentTransportError, "agent_transport_error", False),
    (AgentPayloadTooLargeError, "payload_too_large", False),
    (AgentHandlerError, "agent_handler_error", False),
)


def describe_failure(exc: Exception) -> tuple[str, str, FailureInfo]:
    """``(code, message, FailureInfo)`` for a failed call; free text only where it is safe."""
    if isinstance(exc, OutputRejectedError):
        return (
            "output_rejected",
            str(exc),
            FailureInfo(phase="agent", kind="output_rejected", hint="check_agent"),
        )
    for error_type, code, retryable in _CODES:
        if isinstance(exc, error_type):
            kind = exc.kind if isinstance(exc, AgentCallError) else "unknown"
            return (
                code,
                str(exc),
                FailureInfo(
                    phase="agent",
                    kind=kind,  # type: ignore[arg-type]
                    retryable=retryable,
                    exception_type=type(exc).__name__,
                    hint="check_agent",
                ),
            )
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
