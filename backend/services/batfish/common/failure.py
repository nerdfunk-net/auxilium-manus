"""Map Batfish errors to a :class:`models.failure.FailureInfo`.

Never copies message text (the coordinator's own text is not ours to store); inputs are the
exception class and the transport cause chain (mirrors ``services/pyats/common/failure.py``).
The Batfish coordinator has no authentication of its own here, so there is no ``auth_failed``.
"""

from __future__ import annotations

from models.failure import FailureHint, FailureInfo, FailureKind
from services.batfish.common.exceptions import (
    BatfishAnswerFailedError,
    BatfishAPIError,
    BatfishError,
    BatfishValidationError,
)
from services.network.transport_failure import cause_chain, transport_kind

_HINTS: dict[FailureKind, FailureHint] = {
    "timeout": "check_reachability",
    "refused": "check_reachability",
    "dns": "check_hostname",
    "no_route": "check_reachability",
    "tls_error": "check_tls",
    "bad_request": "check_request",
    "server_error": "check_controller",
}

_RETRYABLE: frozenset[FailureKind] = frozenset({"timeout", "no_route", "server_error"})


def _has_timeout_in_chain(exc: BaseException) -> bool:
    # ``requests`` raises its own ``ReadTimeout`` / ``ConnectTimeout``, which are not the
    # builtin ``TimeoutError``; only the class name is inspected.
    return any("timeout" in type(err).__name__.lower() for err in cause_chain(exc))


def _kind(exc: BatfishError) -> FailureKind:
    if isinstance(exc, (BatfishValidationError, BatfishAnswerFailedError)):
        return "bad_request"
    if isinstance(exc, BatfishAPIError):
        transport = transport_kind(exc)
        if transport is not None:
            return transport
        if _has_timeout_in_chain(exc):
            return "timeout"
        return "server_error"
    return "server_error"


def classify_batfish_exception(exc: BatfishError) -> FailureInfo:
    kind = _kind(exc)
    return FailureInfo(
        phase="api",
        kind=kind,
        retryable=kind in _RETRYABLE,
        exception_type=type(exc).__name__,
        hint=_HINTS.get(kind),
    )
