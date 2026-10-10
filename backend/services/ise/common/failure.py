"""Map Cisco ISE errors to a :class:`models.failure.FailureInfo`.

Never copies message text; inputs are the exception class, ``http_status``, ``code`` and the
transport cause chain. ISE ERS uses HTTP basic auth on every request, so a 401 is a credential
problem (``auth_failed``) and a 403 a missing ERS permission (``permission_denied``).
"""

from __future__ import annotations

from models.failure import FailureHint, FailureInfo, FailureKind
from services.ise.common.exceptions import (
    ISEAPIError,
    ISEError,
    ISENotFoundError,
    ISEValidationError,
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
}

_RETRYABLE: frozenset[FailureKind] = frozenset(
    {"timeout", "no_route", "rate_limited", "server_error"}
)


def _kind(exc: ISEError) -> FailureKind:
    status = exc.http_status
    if isinstance(exc, ISENotFoundError):
        return "not_found"
    if isinstance(exc, ISEValidationError):
        return "bad_request"
    if isinstance(exc, ISEAPIError):
        if exc.code == "timeout":
            return "timeout"
        if exc.code == "invalid_response":
            return "invalid_response"
        if status == 401:
            return "auth_failed"
        if status == 403:
            return "permission_denied"
        if status == 429:
            return "rate_limited"
        if status is not None and status >= 500:
            return "server_error"
        transport = transport_kind(exc)
        if transport is not None:
            return transport
        if status is not None:
            return "bad_request"
    return "unknown"


def classify_ise_exception(exc: ISEError) -> FailureInfo:
    kind = _kind(exc)
    return FailureInfo(
        phase="auth" if kind == "auth_failed" else "api",
        kind=kind,
        retryable=kind in _RETRYABLE,
        http_status=exc.http_status,
        exception_type=type(exc).__name__,
        hint=_HINTS.get(kind),
    )
