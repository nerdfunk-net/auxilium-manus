"""Map pyATS shim errors to a :class:`models.failure.FailureInfo`.

Never copies message text; inputs are the exception class, ``http_status``, ``code`` and the
transport cause chain (mirrors ``services/ise/common/failure.py``). The shim authenticates with a
bearer token, so a 401 is a credential problem and a 403 a missing permission.
"""

from __future__ import annotations

from models.failure import FailureHint, FailureInfo, FailureKind
from services.network.transport_failure import transport_kind
from services.pyats.common.exceptions import PyATSAPIError, PyATSError, PyATSValidationError

_HINTS: dict[FailureKind, FailureHint] = {
    "timeout": "check_reachability",
    "refused": "check_reachability",
    "dns": "check_hostname",
    "no_route": "check_reachability",
    "tls_error": "check_tls",
    "auth_failed": "check_credentials",
    "permission_denied": "check_permissions",
    "rate_limited": "retry_later",
    "bad_request": "check_request",
    "server_error": "check_controller",
}

_RETRYABLE: frozenset[FailureKind] = frozenset(
    {"timeout", "no_route", "rate_limited", "server_error"}
)


def _kind(exc: PyATSError) -> FailureKind:
    status = exc.http_status
    if isinstance(exc, PyATSValidationError):
        return "bad_request"
    if isinstance(exc, PyATSAPIError):
        if exc.code == "timeout":
            return "timeout"
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


def classify_pyats_exception(exc: PyATSError) -> FailureInfo:
    kind = _kind(exc)
    return FailureInfo(
        phase="auth" if kind == "auth_failed" else "api",
        kind=kind,
        retryable=kind in _RETRYABLE,
        http_status=exc.http_status,
        exception_type=type(exc).__name__,
        hint=_HINTS.get(kind),
    )
