"""Classify low-level transport errors (sockets, DNS, TLS) into a ``FailureKind``.

Shared by every client that talks over the network (Netmiko, httpx based API clients). Walks
the ``__cause__`` / ``__context__`` chain because libraries wrap the OS error. Only inspects
exception types, errno values and message text; never returns any of it.
"""

from __future__ import annotations

import errno
import socket
import ssl

from models.failure import FailureKind

MAX_CAUSE_DEPTH = 5

_NO_ROUTE_ERRNOS = frozenset(
    {errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EHOSTDOWN, errno.ENETDOWN}
)

# (substring of the lower-cased message, kind); first match wins.
_MESSAGE_CAUSES: tuple[tuple[str, FailureKind], ...] = (
    ("connection refused", "refused"),
    ("name or service not known", "dns"),
    ("nodename nor servname", "dns"),
    ("getaddrinfo failed", "dns"),
    ("temporary failure in name resolution", "dns"),
    ("no route to host", "no_route"),
    ("network is unreachable", "no_route"),
)


def cause_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and len(chain) < MAX_CAUSE_DEPTH:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _kind_from_os_error(err: BaseException) -> FailureKind | None:
    if isinstance(err, ssl.SSLError):
        return "tls_error"
    if isinstance(err, socket.gaierror):
        return "dns"
    if isinstance(err, ConnectionRefusedError):
        return "refused"
    if isinstance(err, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(err, OSError) and err.errno in _NO_ROUTE_ERRNOS:
        return "no_route"
    return None


def transport_kind(exc: BaseException) -> FailureKind | None:
    """The transport-level cause somewhere in the chain of *exc*, or ``None``."""
    for err in cause_chain(exc):
        kind = _kind_from_os_error(err)
        if kind is not None:
            return kind
        message = str(err).lower()
        for needle, message_kind in _MESSAGE_CAUSES:
            if needle in message:
                return message_kind
    return None
