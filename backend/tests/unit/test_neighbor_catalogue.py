"""The reviewed command catalogue for neighbour discovery (doc/AI_TOOL_CHAIN.md §24.5)."""

from __future__ import annotations

import pytest
from ntc_templates.parse import ParsingException, parse_output

from services.ai_assistant.command_policy import check_command
from services.ai_assistant.neighbors import catalogue as cat

ALL_PROTOCOLS = ("routing_table", "ospf", "bgp", "eigrp", "isis")


def _every_plan():
    for family in cat.FAMILIES:
        for layer in ("l2", "l3"):
            for protocol in (*ALL_PROTOCOLS, "discover"):
                for vrf in ("default", "BLUE"):
                    try:
                        yield family, cat.plan_discovery(family, layer, protocol, vrf)
                    except cat.UnsupportedDiscoveryError:
                        continue


def test_every_catalogued_command_passes_the_read_only_policy() -> None:
    count = 0
    for _, plan in _every_plan():
        for step in plan.steps:
            assert check_command(step.command) == step.command
            count += 1
    assert count > 40


_NTC_TYPE = {
    "ios": "cisco_ios",
    "nxos": "cisco_nxos",
    "xr": "cisco_xr",
    "eos": "arista_eos",
    "junos": "juniper_junos",
}


def _has_template(family: str, command: str) -> bool:
    """True when ntc-templates picks a template for the command (an empty output is fine)."""
    try:
        parse_output(platform=_NTC_TYPE[family], command=command, data="")
    except ParsingException as exc:
        return "No template" not in str(exc) and "not found" not in str(exc).lower()
    return True


def test_every_parsed_command_has_an_installed_template() -> None:
    """Fails the build when a catalogue entry has no parser (§24.14)."""
    missing = [
        (family, step.command)
        for family, plan in _every_plan()
        if plan.parser == "textfsm"
        for step in plan.steps
        if not _has_template(family, step.command)
    ]
    assert missing == []


@pytest.mark.parametrize(
    ("driver", "family"),
    [
        ("cisco_ios", "ios"),
        ("cisco_xe", "ios"),
        ("cisco_nxos", "nxos"),
        ("cisco_xr", "xr"),
        ("arista_eos", "eos"),
        ("juniper_junos", "junos"),
        ("hp_comware", None),
        ("cisco_asa", None),
        (None, None),
    ],
)
def test_family_of_a_netmiko_type(driver: str | None, family: str | None) -> None:
    assert cat.family_of(driver) == family


def test_l2_on_ios_asks_cdp_and_lldp_detail() -> None:
    plan = cat.plan_discovery("ios", "l2", "routing_table", "default")
    assert [s.command for s in plan.steps] == [
        "show cdp neighbors detail",
        "show lldp neighbors detail",
    ]
    assert plan.parser == "textfsm"


def test_junos_has_lldp_only_and_no_routing_table() -> None:
    assert [
        s.command for s in cat.plan_discovery("junos", "l2", "routing_table", "default").steps
    ] == ["show lldp neighbors"]
    with pytest.raises(cat.UnsupportedDiscoveryError):
        cat.plan_discovery("junos", "l3", "routing_table", "default")


def test_a_vrf_uses_the_vrf_form_or_is_refused() -> None:
    plan = cat.plan_discovery("nxos", "l3", "routing_table", "BLUE")
    assert [s.command for s in plan.steps] == ["show ip route vrf BLUE"]
    assert plan.steps[0].vrf == "BLUE"
    with pytest.raises(cat.UnsupportedDiscoveryError):
        cat.plan_discovery("ios", "l3", "ospf", "BLUE")


@pytest.mark.parametrize("vrf", ["a b", "x;reload", "", "a" * 33, "../x", "vrf|include"])
def test_a_bad_vrf_name_is_refused(vrf: str) -> None:
    with pytest.raises(cat.UnsupportedDiscoveryError):
        cat.plan_discovery("ios", "l3", "routing_table", vrf)


def test_both_layers_combine_and_stay_within_the_command_limit() -> None:
    plan = cat.plan_discovery("ios", "both", "ospf", "default")
    assert [s.layer for s in plan.steps] == ["l2", "l2", "l3"]
    assert len(plan.steps) <= 5


def test_discovery_of_protocols_is_raw_text() -> None:
    plan = cat.plan_discovery("ios", "l3", "discover", "default")
    assert plan.parser == "none"
    assert "show ip protocols" in [s.command for s in plan.steps]


def test_unknown_platform_family_has_no_plan() -> None:
    with pytest.raises(cat.UnsupportedDiscoveryError):
        cat.plan_discovery("comware", "l2", "routing_table", "default")


def test_classify_gives_back_what_the_plan_asked() -> None:
    for family, plan in _every_plan():
        for step in plan.steps:
            found = cat.classify_command(family, step.command)
            assert found is not None, (family, step.command)
            assert (found.layer, found.protocol, found.vrf) == (
                step.layer,
                step.protocol,
                step.vrf,
            ), (family, step.command)


def test_classify_ignores_commands_that_are_not_neighbour_commands() -> None:
    assert cat.classify_command("ios", "show version") is None
    assert cat.classify_command("ios", "show ip route vrf X; reload") is None
    assert cat.classify_command("nope", "show ip route") is None
