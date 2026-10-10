"""Map Nautobot errors to a :class:`models.failure.FailureInfo`.

Never copies message text (Nautobot error messages include response bodies). Inputs are the
exception class, ``http_status``, ``code`` and the transport cause chain.
"""

from __future__ import annotations

from models.failure import FailureHint, FailureInfo, FailureKind
from services.nautobot.common.exceptions import (
    NautobotAPIError,
    NautobotDuplicateResourceError,
    NautobotError,
    NautobotNotFoundError,
    NautobotResourceNotFoundError,
    NautobotValidationError,
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
    "already_exists": "check_request",
    "server_error": "check_controller",
}

_RETRYABLE: frozenset[FailureKind] = frozenset(
    {"timeout", "no_route", "rate_limited", "server_error"}
)

_STATUS_KINDS: dict[int, FailureKind] = {
    400: "bad_request",
    401: "auth_failed",
    403: "permission_denied",
    404: "not_found",
    409: "already_exists",
    429: "rate_limited",
}


def _kind(exc: NautobotError) -> FailureKind:
    if isinstance(exc, NautobotDuplicateResourceError):
        return "already_exists"
    if isinstance(exc, (NautobotNotFoundError, NautobotResourceNotFoundError)):
        return "not_found"
    if isinstance(exc, NautobotValidationError):
        return "bad_request"
    if isinstance(exc, NautobotAPIError):
        if exc.code == "timeout":
            return "timeout"
        status = exc.http_status
        if status is not None:
            if status in _STATUS_KINDS:
                return _STATUS_KINDS[status]
            if status >= 500:
                return "server_error"
            return "bad_request"
        transport = transport_kind(exc)
        if transport is not None:
            return transport
    return "unknown"


def classify_nautobot_exception(exc: NautobotError) -> FailureInfo:
    kind = _kind(exc)
    return FailureInfo(
        phase="auth" if kind == "auth_failed" else "api",
        kind=kind,
        retryable=kind in _RETRYABLE,
        http_status=exc.http_status,
        exception_type=type(exc).__name__,
        hint=_HINTS.get(kind),
    )
