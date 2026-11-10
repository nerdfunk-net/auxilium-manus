"""``SystemDnsResolver``: stdlib lookups mapped to a status, never an exception."""

from __future__ import annotations

import asyncio
import socket
import time
from typing import Any
from unittest.mock import patch

import pytest

from services.ai_assistant.dns_resolver import SystemDnsResolver


def _info(address: str, canon: str = "") -> tuple[Any, ...]:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, canon, (address, 0))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_forward_returns_sorted_unique_addresses_and_the_canonical_name() -> None:
    infos = [
        _info("10.0.0.9", "lab.local.zz"),
        _info("10.0.0.2"),
        _info("10.0.0.9"),
        _info("fd00::1"),
    ]
    with patch("services.ai_assistant.dns_resolver.socket.getaddrinfo", return_value=infos):
        answer = _run(SystemDnsResolver(("local.zz",)).forward("lab.local.zz"))

    assert answer.status == "found"
    assert answer.values == ("10.0.0.2", "10.0.0.9", "fd00::1")
    assert answer.canonical_name == "lab.local.zz"


def test_an_ipv6_scope_id_is_dropped_from_an_address() -> None:
    with patch(
        "services.ai_assistant.dns_resolver.socket.getaddrinfo",
        return_value=[(socket.AF_INET6, 1, 6, "", ("fe80::1%eth0", 0, 0, 2))],
    ):
        answer = _run(SystemDnsResolver(("local.zz",)).forward("lab.local.zz"))
    assert answer.values == ("fe80::1",)


def test_an_unknown_name_is_not_found() -> None:
    err = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    with patch("services.ai_assistant.dns_resolver.socket.getaddrinfo", side_effect=err):
        answer = _run(SystemDnsResolver(("local.zz",)).forward("nope.local.zz"))
    assert (answer.status, answer.values) == ("not_found", ())


def test_a_temporary_failure_is_unavailable() -> None:
    err = socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
    with patch("services.ai_assistant.dns_resolver.socket.getaddrinfo", side_effect=err):
        answer = _run(SystemDnsResolver(("local.zz",)).forward("lab.local.zz"))
    assert answer.status == "unavailable"


def test_reverse_returns_the_name_and_aliases() -> None:
    with patch(
        "services.ai_assistant.dns_resolver.socket.gethostbyaddr",
        return_value=("one.one.one.one", ["alias.example"], ["1.1.1.1"]),
    ):
        answer = _run(SystemDnsResolver(()).reverse("1.1.1.1"))
    assert answer.status == "found"
    assert answer.values == ("alias.example", "one.one.one.one")


@pytest.mark.parametrize("code", [1, 4])
def test_reverse_without_a_record_is_not_found(code: int) -> None:
    with patch(
        "services.ai_assistant.dns_resolver.socket.gethostbyaddr",
        side_effect=socket.herror(code, "Unknown host"),
    ):
        assert _run(SystemDnsResolver(()).reverse("192.0.2.1")).status == "not_found"


def test_reverse_that_echoes_the_address_is_not_found() -> None:
    with patch(
        "services.ai_assistant.dns_resolver.socket.gethostbyaddr",
        return_value=("192.0.2.1", [], ["192.0.2.1"]),
    ):
        assert _run(SystemDnsResolver(()).reverse("192.0.2.1")).status == "not_found"


def test_another_reverse_error_is_unavailable() -> None:
    with patch(
        "services.ai_assistant.dns_resolver.socket.gethostbyaddr",
        side_effect=socket.herror(2, "Host name lookup failure"),
    ):
        assert _run(SystemDnsResolver(()).reverse("192.0.2.1")).status == "unavailable"


def test_a_slow_resolver_times_out_as_unavailable() -> None:
    def slow(*_a: Any, **_k: Any) -> Any:
        time.sleep(0.5)
        return [_info("10.0.0.1")]

    with patch("services.ai_assistant.dns_resolver.socket.getaddrinfo", side_effect=slow):
        answer = _run(
            SystemDnsResolver(("local.zz",), timeout_seconds=0.05).forward("lab.local.zz")
        )
    assert answer.status == "unavailable"


def test_an_unexpected_error_is_unavailable_not_raised() -> None:
    with patch(
        "services.ai_assistant.dns_resolver.socket.getaddrinfo", side_effect=OSError("boom")
    ):
        assert (
            _run(SystemDnsResolver(("local.zz",)).forward("lab.local.zz")).status == "unavailable"
        )
