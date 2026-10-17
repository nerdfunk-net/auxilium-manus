"""Map Netmiko / paramiko / socket exceptions to a :class:`models.failure.FailureInfo`.

Pure and total: it never raises and never copies exception text into the result (the text can
echo credentials or device output). Message text is only *inspected* to tell apart causes that
Netmiko folds into one exception class.
"""

from __future__ import annotations

from netmiko.exceptions import (
    ConfigInvalidException,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
    ReadTimeout,
)
from paramiko.ssh_exception import AuthenticationException, SSHException

from models.failure import FailureHint, FailureInfo, FailureKind, FailurePhase
from services.network.transport_failure import cause_chain, transport_kind

_HINTS: dict[FailureKind, FailureHint] = {
    "timeout": "check_reachability",
    "refused": "check_ssh_service",
    "dns": "check_hostname",
    "no_route": "check_reachability",
    "auth_failed": "check_credentials",
    "ssh_error": "check_ssh_compatibility",
    "command_timeout": "increase_read_timeout",
    "config_rejected": "check_command_syntax",
}

_RETRYABLE: frozenset[FailureKind] = frozenset({"timeout", "no_route"})


def _connect_kind(exc: BaseException) -> FailureKind:
    if isinstance(exc, (NetmikoAuthenticationException, AuthenticationException)):
        return "auth_failed"
    kind = transport_kind(exc)
    if kind is not None:
        return kind
    if isinstance(exc, NetmikoTimeoutException):
        return "timeout"
    if isinstance(exc, SSHException):
        return "ssh_error"
    return "unknown"


def _command_kind(exc: BaseException) -> FailureKind:
    for err in cause_chain(exc):
        if isinstance(err, ReadTimeout):
            return "command_timeout"
        if isinstance(err, ConfigInvalidException):
            return "config_rejected"
    return "command_error"


def classify_netmiko_exception(
    exc: BaseException,
    *,
    phase: FailurePhase,
    attempts: int | None = None,
    max_attempts: int | None = None,
    elapsed_ms: int | None = None,
) -> FailureInfo:
    kind = _connect_kind(exc) if phase == "connect" else _command_kind(exc)
    return FailureInfo(
        phase=phase,
        kind=kind,
        retryable=kind in _RETRYABLE,
        attempts=attempts,
        max_attempts=max_attempts,
        elapsed_ms=elapsed_ms,
        exception_type=type(exc).__name__,
        hint=_HINTS.get(kind),
    )
