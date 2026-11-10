"""Policy for the DNS lookup tool: which names and addresses may be sent to the resolver."""

from __future__ import annotations

import ipaddress

import pytest

from services.ai_assistant.dns_policy import (
    DnsPolicyError,
    forward_name,
    normalize_suffix,
    normalize_suffixes,
    reverse_address,
)

SUFFIXES = ("local.zz", "corp.example")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("local.zz", "local.zz"), (".Local.ZZ", "local.zz"), ("corp.example.", "corp.example")],
)
def test_a_suffix_is_normalised(raw: str, expected: str) -> None:
    assert normalize_suffix(raw) == expected


@pytest.mark.parametrize("raw", ["", ".", "a b", "-bad.zz", "x" * 64 + ".zz", "a..b", "a_b/c"])
def test_a_bad_suffix_is_refused_at_startup(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_suffix(raw)


def test_suffixes_are_deduplicated_and_ordered() -> None:
    assert normalize_suffixes(["b.zz", "A.zz", "a.zz."]) == ("a.zz", "b.zz")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("LAB.local.zz", "lab.local.zz"),
        ("lab.local.zz.", "lab.local.zz"),
        ("a.b.corp.example", "a.b.corp.example"),
        ("  lab.local.zz  ", "lab.local.zz"),
    ],
)
def test_a_name_under_an_allowed_suffix_passes(name: str, expected: str) -> None:
    assert forward_name(name, SUFFIXES) == expected


@pytest.mark.parametrize(
    "name",
    [
        "lab.example.com",  # outside
        "xlocal.zz",  # not on a label boundary
        "local.zz",  # the suffix itself is not a host
        "lab",  # single label: search-domain expansion would bypass the check
        "secret.attacker.com.local.zz.evil.com",
        "lab local.zz",
        "lab.local.zz/../x",
        "lab_.local.zz\n",
        "-lab.local.zz",
        ("a" * 64) + ".local.zz",
        ("a." * 130) + "local.zz",
        "1.2.3.local.zz\x00",
        "lab.local.zz@evil.com",
    ],
)
def test_other_names_are_refused(name: str) -> None:
    with pytest.raises(DnsPolicyError):
        forward_name(name, SUFFIXES)


def test_no_suffixes_means_no_forward_lookup() -> None:
    with pytest.raises(DnsPolicyError, match="AI_DNS_ALLOWED_SUFFIXES"):
        forward_name("lab.local.zz", ())


def test_the_refusal_names_the_allowed_suffixes() -> None:
    with pytest.raises(DnsPolicyError, match="local.zz, corp.example"):
        forward_name("lab.example.com", SUFFIXES)


@pytest.mark.parametrize("text", ["1.1.1.1", "10.0.0.5", "2001:4860:4860::8888", "fd00::1"])
def test_ordinary_addresses_pass_a_reverse_lookup(text: str) -> None:
    assert reverse_address(text) == ipaddress.ip_address(text)


@pytest.mark.parametrize(
    "text",
    [
        "127.0.0.1",
        "::1",
        "169.254.169.254",
        "fe80::1",
        "0.0.0.0",
        "224.0.0.1",
        "ff02::1",
        "240.0.0.1",
    ],
)
def test_special_addresses_are_refused(text: str) -> None:
    with pytest.raises(DnsPolicyError):
        reverse_address(text)


def test_an_ipv6_scope_id_is_refused() -> None:
    with pytest.raises(DnsPolicyError):
        reverse_address("fe80::1%eth0")
