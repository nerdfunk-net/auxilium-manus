"""Permitted-prefix parsing and the host policy of the discover-network step."""

from __future__ import annotations

import ipaddress

import pytest

from workflow_steps.discover_network.scope import (
    MAX_PREFIXES,
    check_discovered_host,
    ensure_following_allowed,
    in_scope,
    parse_prefixes,
)


def test_parses_list_and_text_forms_and_deduplicates() -> None:
    expected = (ipaddress.ip_network("10.1.0.0/16"), ipaddress.ip_network("192.168.5.0/24"))
    assert parse_prefixes(["10.1.0.0/16", " 192.168.5.0/24 ", "10.1.0.0/16"]) == expected
    assert parse_prefixes("10.1.0.0/16\n192.168.5.0/24, 10.1.0.0/16") == expected


def test_empty_input_gives_no_prefixes() -> None:
    assert parse_prefixes(None) == ()
    assert parse_prefixes("  \n ") == ()
    assert parse_prefixes([]) == ()


@pytest.mark.parametrize(
    "bad",
    [
        "10.1.0.0",  # no mask: a single host is not a prefix
        "10.1.0.5/24",  # host bits set
        "not-a-prefix",
        "2001:db8::/32",  # IPv6
        "0.0.0.0/0",
        "10.0.0.0/7",  # broader than /8
        "127.0.0.0/8",  # loopback
        "169.254.0.0/16",  # link local / cloud metadata
        "224.0.0.0/4",  # multicast
    ],
)
def test_rejects_unsafe_or_malformed_prefixes(bad: str) -> None:
    with pytest.raises(ValueError, match="discover-network"):
        parse_prefixes([bad])


def test_rejects_a_prefix_that_overlaps_a_blocked_range() -> None:
    with pytest.raises(ValueError, match="discover-network"):
        parse_prefixes(["168.0.0.0/8", "169.0.0.0/8"])  # 169.0/8 contains 169.254/16


def test_rejects_too_many_prefixes() -> None:
    many = [f"10.{i}.0.0/16" for i in range(MAX_PREFIXES + 1)]
    with pytest.raises(ValueError, match="at most"):
        parse_prefixes(many)


def test_non_string_entry_is_rejected() -> None:
    with pytest.raises(ValueError, match="discover-network"):
        parse_prefixes([10])  # type: ignore[list-item]


def test_in_scope() -> None:
    prefixes = parse_prefixes(["10.1.0.0/16", "192.168.5.0/24"])
    assert in_scope("10.1.200.9", prefixes)
    assert in_scope("192.168.5.254", prefixes)
    assert not in_scope("10.2.0.1", prefixes)
    assert not in_scope("192.168.6.1", prefixes)
    assert not in_scope("not-an-ip", prefixes)
    assert not in_scope("2001:db8::1", prefixes)
    assert not in_scope("10.1.0.1", ())


def test_host_policy_blocks_special_addresses() -> None:
    for host in (
        "127.0.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "0.0.0.0",
        "metadata.google.internal",
    ):
        with pytest.raises(ValueError):
            check_discovered_host(host)
    check_discovered_host("10.1.0.5")


def test_following_needs_the_dedicated_operator_switch() -> None:
    with pytest.raises(ValueError, match="DISCOVER_NETWORK_FOLLOW_ENABLED"):
        ensure_following_allowed(enabled=False)
    ensure_following_allowed(enabled=True)


def test_following_does_not_depend_on_the_preview_only_host_switch() -> None:
    # ALLOW_NETMIKO_ARBITRARY_HOSTS cannot be set outside development (startup refuses it),
    # so neither the message nor the check may mention it.
    with pytest.raises(ValueError) as excinfo:
        ensure_following_allowed(enabled=False)
    assert "ARBITRARY" not in str(excinfo.value)
