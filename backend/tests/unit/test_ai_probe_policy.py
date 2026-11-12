"""Ping and traceroute: the probe grammar and the command builder (doc/AI_TOOL_CHAIN.md §51)."""

from __future__ import annotations

import pytest

from services.ai_assistant import command_policy as cp
from services.ai_assistant import probes

TARGET = "192.168.178.241"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"ping {TARGET}", f"ping {TARGET}"),
        (f"  PING   {TARGET} ", f"ping {TARGET}"),
        (f"traceroute {TARGET}", f"traceroute {TARGET}"),
        (
            f"ping vrf MGMT {TARGET} repeat 5 timeout 2 source 10.0.0.1",
            f"ping vrf MGMT {TARGET} repeat 5 timeout 2 source 10.0.0.1",
        ),
        (
            f"ping {TARGET} count 5 routing-instance MGMT no-resolve",
            f"ping {TARGET} count 5 routing-instance MGMT no-resolve",
        ),
        (
            f"traceroute vrf A {TARGET} numeric timeout 1 probe 1 ttl 1 30",
            f"traceroute vrf A {TARGET} numeric timeout 1 probe 1 ttl 1 30",
        ),
    ],
)
def test_probe_commands_are_allowed_and_normalised(raw: str, expected: str) -> None:
    assert cp.check_probe_command(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ping",
        "traceroute",
        "ping example.com",  # names leave the building in a DNS query
        f"ping {TARGET} {TARGET}",  # two targets
        f"ping {TARGET} count 11",  # more than the cap
        f"ping {TARGET} count 0",
        f"ping {TARGET} repeat 100000",
        f"ping {TARGET} timeout 60",
        f"ping {TARGET} size 65000",  # not a known keyword
        f"ping {TARGET} count",  # value missing
        f"ping {TARGET} source lo0",  # source is an address only
        f"ping {TARGET} vrf",
        f"ping vrf 'a;b' {TARGET}",
        f"ping {TARGET} | include x",  # no pipes on a probe
        f"ping {TARGET}; reload",
        f"ping {TARGET}\nreload",
        f"ping {TARGET} && show version",
        "ping 127.0.0.1",
        "ping 0.0.0.0",
        "ping 224.0.0.5",
        "ping 169.254.169.254",
        "ping 255.255.255.255",
        "ping 240.0.0.1",
        "ping ::1",  # IPv6 is not supported yet
        "ping ::ffff:127.0.0.1",
        "ping 10.0.0.1%eth0",
        "ping 10.0.0.256",
        "ping 010.0.0.1",
        "telnet 10.0.0.1",
        "ssh 10.0.0.1",
        "pingg 10.0.0.1",
        "show version",
        "ping⁠ 10.0.0.1",
        "",
    ],
)
def test_everything_else_is_refused(raw: str) -> None:
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_probe_command(raw)


def test_a_free_form_show_command_still_refuses_ping() -> None:
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_command(f"ping {TARGET}")
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_commands([f"traceroute {TARGET}"])


def test_the_signed_path_accepts_show_and_probe_commands_together() -> None:
    commands = ["show version", f"ping {TARGET}", f"traceroute {TARGET}"]

    assert cp.check_commands(commands, allow_probes=True) == commands


def test_the_signed_path_still_refuses_other_verbs() -> None:
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_commands(["ping 10.0.0.1 count 3", "reload"], allow_probes=True)


@pytest.mark.parametrize("family", probes.FAMILIES)
@pytest.mark.parametrize("vrf", ["default", "MGMT"])
@pytest.mark.parametrize("source", [None, "10.9.9.9"])
def test_every_built_command_passes_the_policy(family: str, vrf: str, source) -> None:
    commands = probes.plan_probes(family, "both", TARGET, vrf, 5, source)

    assert len(commands) == 2
    assert [cp.check_probe_command(c) for c in commands] == commands
    assert commands[0].startswith("ping ") and commands[1].startswith("traceroute ")
    assert all(TARGET in c for c in commands)
    assert (vrf in commands[0]) == (vrf != "default")


def test_junos_ping_is_always_bounded_by_a_count() -> None:
    (command,) = probes.plan_probes("junos", "ping", TARGET, "default", 3, None)

    assert "count 3" in command  # Junos pings forever without it
    assert "no-resolve" in command


def test_each_family_spells_vrf_and_count_its_own_way() -> None:
    ios = probes.plan_probes("ios", "ping", TARGET, "V1", 4, None)[0]
    nxos = probes.plan_probes("nxos", "ping", TARGET, "V1", 4, None)[0]
    junos = probes.plan_probes("junos", "ping", TARGET, "V1", 4, None)[0]

    assert ios.startswith("ping vrf V1 ") and "repeat 4" in ios
    assert nxos.startswith(f"ping {TARGET} ") and "vrf V1" in nxos and "count 4" in nxos
    assert "routing-instance V1" in junos


def test_kind_selects_the_commands() -> None:
    assert [
        c.split()[0] for c in probes.plan_probes("ios", "ping", TARGET, "default", 5, None)
    ] == ["ping"]
    assert [
        c.split()[0] for c in probes.plan_probes("ios", "traceroute", TARGET, "default", 5, None)
    ] == ["traceroute"]


def test_an_unsupported_family_or_target_is_refused_with_a_safe_message() -> None:
    with pytest.raises(probes.UnsupportedProbeError):
        probes.plan_probes("comware", "ping", TARGET, "default", 5, None)
    with pytest.raises(cp.CommandNotAllowedError):
        probes.plan_probes("ios", "ping", "example.com", "default", 5, None)
    with pytest.raises(cp.CommandNotAllowedError):
        probes.plan_probes("ios", "ping", "127.0.0.1", "default", 5, None)
    with pytest.raises(cp.CommandNotAllowedError):
        probes.plan_probes("ios", "ping", TARGET, "bad vrf;x", 5, None)


# -- review fixes (doc/analysis/REVIEW.md) ----------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        f"ping {TARGET} source 10.0.0.1 source 8.8.8.8",  # a keyword twice
        f"ping {TARGET} count 10 count 10",
        f"ping {TARGET} numeric numeric",
        f"ping {TARGET} count 5 repeat 5",  # two spellings of one setting
        f"ping vrf A {TARGET} routing-instance B",  # two VRF spellings
        f"traceroute {TARGET} ttl 30 1",  # minimum above maximum
        f"traceroute {TARGET} ttl 1",  # one number
        f"traceroute {TARGET} ttl 1 1 1",
        f"ping vrf count {TARGET} repeat 5",  # a VRF named like a keyword
        f"ping vrf source {TARGET}",
        "ping 0.1.2.3",  # 0.0.0.0/8
        "ping 100.100.100.200",  # Alibaba Cloud metadata
        f"ping {TARGET} source 0.1.2.3",
    ],
)
def test_the_grammar_is_no_wider_than_the_builder(raw: str) -> None:
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_probe_command(raw)


def test_every_built_command_still_passes_after_tightening() -> None:
    for family in probes.FAMILIES:
        for kind in ("ping", "traceroute", "both"):
            for vrf in ("default", "V1"):
                for source in (None, "10.9.9.9"):
                    commands = probes.plan_probes(family, kind, TARGET, vrf, 5, source)
                    assert [cp.check_probe_command(c) for c in commands] == commands


def test_the_traceroute_of_every_family_without_a_knob_is_the_only_unbounded_one() -> None:
    # Families whose CLI has the knobs are bounded and never resolve names; NX-OS and EOS have none.
    bounded = {"ios": "ttl 1 30", "xr": "maxttl 20", "junos": "wait 1"}
    for family, token in bounded.items():
        (command,) = probes.plan_probes(family, "traceroute", TARGET, "default", 5, None)
        assert token in command
        assert "numeric" in command or "no-resolve" in command
    for family in ("nxos", "eos"):
        assert family in probes.UNBOUNDED_TRACEROUTE_FAMILIES


def test_a_family_added_without_a_builder_branch_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(probes, "FAMILIES", (*probes.FAMILIES, "newos"))

    with pytest.raises(probes.UnsupportedProbeError):
        probes.plan_probes("newos", "ping", TARGET, "default", 5, None)
