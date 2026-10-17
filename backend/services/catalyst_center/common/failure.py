"""Map Catalyst Center errors to a :class:`models.failure.FailureInfo`.

Never copies message text. The inputs are the exception class, ``http_status``, ``code`` and
(for transport errors) the cause chain.

``code`` values set at raise sites: ``token_rejected`` (credentials refused at login),
``request_denied`` (401/403 on a normal request), ``timeout``, ``transport``,
``invalid_response``, ``task_failed``, ``task_timeout``.
"""

from __future__ import annotations

from models.failure import FailureHint, FailureInfo, FailureKind, FailurePhase
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterError,
    CatalystCenterNotFoundError,
    CatalystCenterRateLimitError,
    CatalystCenterTaskError,
    CatalystCenterValidationError,
)
from services.network.transport_failure import transport_kind

_HINTS: dict[FailureKind, FailureHint] = {
    "timeout": "check_reachability",
    "refused": "check_reachability",
    "dns": "check_hostname",
    "no_route": "check_reachability",
    "tls_error": "check_tls",
    "auth_failed": "check_credentials",
    "permission_denied": "check_permissions",
    "rate_limited": "retry_later",
    "not_found": "check_request",
    "bad_request": "check_request",
    "server_error": "check_controller",
    "invalid_response": "check_controller",
    "task_failed": "check_controller",
    "task_timeout": "check_controller",
}

_RETRYABLE: frozenset[FailureKind] = frozenset(
    {"timeout", "no_route", "rate_limited", "server_error", "task_timeout"}
)


def _kind_and_phase(exc: CatalystCenterError) -> tuple[FailureKind, FailurePhase]:
    if isinstance(exc, CatalystCenterAuthError):
        if exc.code == "token_rejected":
            return "auth_failed", "auth"
        return "permission_denied", "api"
    if isinstance(exc, CatalystCenterRateLimitError):
        return "rate_limited", "api"
    if isinstance(exc, CatalystCenterNotFoundError):
        return "not_found", "api"
    if isinstance(exc, CatalystCenterValidationError):
        return "bad_request", "api"
    if isinstance(exc, CatalystCenterTaskError):
        if exc.code == "task_timeout":
            return "task_timeout", "task"
        if exc.code == "invalid_response":
            return "invalid_response", "task"
        return "task_failed", "task"
    if isinstance(exc, CatalystCenterAPIError):
        if exc.code == "timeout":
            return "timeout", "api"
        if exc.code == "invalid_response":
            return "invalid_response", "api"
        if exc.http_status is not None and exc.http_status >= 500:
            return "server_error", "api"
        transport = transport_kind(exc)
        if transport is not None:
            return transport, "api"
        if exc.http_status is not None:
            return "bad_request", "api"
    return "unknown", "api"


def classify_catalyst_center_exception(exc: CatalystCenterError) -> FailureInfo:
    kind, phase = _kind_and_phase(exc)
    return FailureInfo(
        phase=phase,
        kind=kind,
        retryable=kind in _RETRYABLE,
        http_status=exc.http_status,
        exception_type=type(exc).__name__,
        hint=_HINTS.get(kind),
    )
