"""Parsing of LLDP/CDP neighbours and port-channels for the collect-client-data step."""

from __future__ import annotations

import json

import pytest

from workflow_steps.collect_client_data import commands
from workflow_steps.collect_client_data.parsing import (
    STATUS_NO_TEMPLATE,
    STATUS_NOT_SUPPORTED,
    STATUS_OK,
    NeighborEntry,
    classify_output,
    combine_neighbor_statuses,
    normalise_port,
    parse_capabilities,
    parse_channels,
    parse_neighbors,
)

# -- ports ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "platform", "expected"),
    [
        ("GigabitEthernet1/0/5", "cisco_ios", "Gi1/0/5"),
        ("Gi1/0/5", "cisco_ios", "Gi1/0/5"),
        ("gi1/0/5", "cisco_ios", "Gi1/0/5"),
        ("TenGigabitEthernet1/1/1", "cisco_xe", "Te1/1/1"),
        ("FastEthernet0/1", "cisco_ios", "Fa0/1"),
        ("TwentyFiveGigE1/0/1", "cisco_xe", "Twe1/0/1"),
        ("HundredGigE1/0/1", "cisco_xe", "Hu1/0/1"),
        ("Port-channel12", "cisco_ios", "Po12"),
        ("Po12", "cisco_nxos", "Po12"),
        ("Ethernet1/5", "cisco_nxos", "Eth1/5"),
        ("Eth1/5", "cisco_nxos", "Eth1/5"),
        ("Ethernet0/0", "cisco_ios", "Et0/0"),
        ("  Gi1/0/5 ", "cisco_ios", "Gi1/0/5"),
        ("mgmt0", "cisco_nxos", "mgmt0"),
        ("Vlan10", "cisco_ios", "Vlan10"),
    ],
)
def test_ports_are_normalised_to_the_short_form_the_mac_table_uses(
    raw: str, platform: str, expected: str
) -> None:
    assert normalise_port(raw, platform) == expected


# -- capabilities --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "protocol", "expected"),
    [
        ("B,R", "lldp", ("bridge", "router")),
        ("B, R", "lldp", ("bridge", "router")),
        ("W", "lldp", ("wlan_ap",)),
        ("T", "lldp", ("telephone",)),
        ("S", "lldp", ("station",)),
        ("", "lldp", ()),
        ("Router Switch IGMP", "cdp", ("bridge", "router")),
        ("Router Source-Route-Bridge", "cdp", ("bridge", "router")),
        ("Host Phone", "cdp", ("station", "telephone")),
        ("Switch IGMP Filtering Supports-STP-Dispute", "cdp", ("bridge",)),
        ("R S I", "cdp", ("bridge", "router")),
        ("H P", "cdp", ("station", "telephone")),
        ("r", "cdp", ("repeater",)),  # lower-case r is Repeater, capital R is Router
        ("R", "cdp", ("router",)),
        ("Something New", "cdp", ()),
    ],
)
def test_capabilities_become_a_closed_vocabulary(
    raw: str, protocol: str, expected: tuple[str, ...]
) -> None:
    assert parse_capabilities(raw, protocol) == expected


# -- neighbours ----------------------------------------------------------------------------------

IOS_LLDP = [
    {
        "local_interface": "Gi1/0/48",
        "neighbor_name": "core1.example.net",
        "neighbor_port_id": "Te1/1/1",
        "neighbor_interface": "TenGigabitEthernet1/1/1",
        "capabilities": "B,R",
    },
    {
        "local_interface": "Gi1/0/7",
        "neighbor_name": "phone-7",
        "neighbor_port_id": "aabb.ccdd.0007",
        "neighbor_interface": "",
        "capabilities": "T",
    },
]
IOS_CDP = [
    {
        "local_interface": "GigabitEthernet1/0/47",
        "neighbor_name": "core2.example.net",
        "neighbor_interface": "TenGigabitEthernet1/1/2",
        "capabilities": "Router Switch IGMP",
    }
]


def test_lldp_rows_become_neighbour_entries() -> None:
    entries = parse_neighbors(IOS_LLDP, "lldp", "cisco_ios")

    assert entries[0] == NeighborEntry(
        port="Gi1/0/48",
        neighbor_name="core1.example.net",
        neighbor_port="TenGigabitEthernet1/1/1",
        protocol="lldp",
        capabilities=("bridge", "router"),
    )
    assert entries[0].is_infrastructure is True
    assert entries[1].is_infrastructure is False  # a phone is an end device
    assert entries[1].neighbor_port == "aabb.ccdd.0007"  # falls back to the port id


def test_cdp_ports_are_normalised() -> None:
    (entry,) = parse_neighbors(IOS_CDP, "cdp", "cisco_ios")

    assert (entry.port, entry.protocol) == ("Gi1/0/47", "cdp")
    assert entry.is_infrastructure is True


def test_a_wlan_access_point_counts_as_infrastructure() -> None:
    (entry,) = parse_neighbors(
        [{"local_interface": "Gi1/0/9", "neighbor_name": "ap1", "capabilities": "W"}],
        "lldp",
        "cisco_ios",
    )

    assert entry.is_infrastructure is True


def test_rows_without_a_local_port_are_skipped() -> None:
    assert parse_neighbors([{"neighbor_name": "x", "capabilities": "B"}], "lldp", "cisco_ios") == []


def test_a_row_without_capabilities_is_not_infrastructure() -> None:
    (entry,) = parse_neighbors(
        [{"local_interface": "Gi1/0/9", "neighbor_name": "unknown"}], "lldp", "cisco_ios"
    )

    assert entry.capabilities == () and entry.is_infrastructure is False


# -- port-channels -------------------------------------------------------------------------------


def test_ios_etherchannel_members_map_to_the_bundle() -> None:
    rows = [
        {"group": "1", "bundle_name": "Po1", "member_interface": ["Gi1/0/47", "Gi1/0/48"]},
        {"group": "2", "bundle_name": "Po2", "member_interface": []},
    ]

    assert parse_channels(rows, "cisco_ios") == {"Gi1/0/47": "Po1", "Gi1/0/48": "Po1"}


def test_nxos_port_channel_members_map_to_the_bundle_and_skip_placeholders() -> None:
    rows = [{"bundle_name": "Po10", "member_interface": ["Eth1/1", "Eth1/2", "--"]}]

    assert parse_channels(rows, "cisco_nxos") == {"Eth1/1": "Po10", "Eth1/2": "Po10"}


def test_channel_names_are_normalised() -> None:
    rows = [{"bundle_name": "Port-channel3", "member_interface": ["GigabitEthernet1/0/1"]}]

    assert parse_channels(rows, "cisco_ios") == {"Gi1/0/1": "Po3"}


# -- status of the two commands --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ((STATUS_OK, STATUS_OK), STATUS_OK),
        ((STATUS_OK, STATUS_NOT_SUPPORTED), STATUS_OK),
        ((STATUS_NOT_SUPPORTED, STATUS_OK), STATUS_OK),
        ((STATUS_NOT_SUPPORTED, STATUS_NOT_SUPPORTED), STATUS_NOT_SUPPORTED),
        # Output that is not a table is not trusted: it must not replace good older data.
        ((STATUS_OK, STATUS_NO_TEMPLATE), STATUS_NO_TEMPLATE),
        ((STATUS_NO_TEMPLATE, STATUS_NOT_SUPPORTED), STATUS_NO_TEMPLATE),
    ],
)
def test_the_neighbour_status_of_lldp_and_cdp_together(
    statuses: tuple[str, str], expected: str
) -> None:
    assert combine_neighbor_statuses(statuses) == expected


# -- classification of the new commands --------------------------------------------------------


@pytest.mark.parametrize("command", [commands.CMD_LLDP, commands.CMD_CDP])
def test_a_disabled_protocol_is_not_supported_not_garbage(command: str) -> None:
    text = "% LLDP is not enabled\n" if "lldp" in command else "% CDP is not enabled\n"

    assert classify_output(text, platform="cisco_ios", command=command).status == (
        STATUS_NOT_SUPPORTED
    )


def test_lldp_with_no_neighbours_is_an_empty_table() -> None:
    raw = "Capability codes:\n    (R) Router, (B) Bridge\n\nTotal entries displayed: 0\n"

    assert classify_output(raw, platform="cisco_ios", command=commands.CMD_LLDP).status == (
        STATUS_OK
    )


def test_blank_neighbour_output_is_never_an_empty_table() -> None:
    # A dropped session prints nothing too: keep the older neighbours instead of replacing them.
    for command in (commands.CMD_LLDP, commands.CMD_CDP):
        assert classify_output("", platform="cisco_ios", command=command).status == (
            STATUS_NO_TEMPLATE
        )


def test_neighbour_rows_pass_through_classification() -> None:
    result = classify_output(json.dumps(IOS_LLDP), platform="cisco_ios", command=commands.CMD_LLDP)

    assert result.status == STATUS_OK and len(result.rows) == 2


def test_a_table_with_entries_that_textfsm_did_not_parse_is_not_empty() -> None:
    raw = "Total entries displayed: 2\nChassis id: aabb.ccdd.0001\nPort id: Gi1/0/1\n"

    for command in (commands.CMD_LLDP, commands.CMD_CDP):
        assert classify_output(raw, platform="cisco_ios", command=command).status == (
            STATUS_NO_TEMPLATE
        )


def test_cdp_prints_the_total_with_its_own_wording_when_empty() -> None:
    raw = "Total cdp entries displayed : 0\n"

    assert classify_output(raw, platform="cisco_ios", command=commands.CMD_CDP).status == (
        STATUS_OK
    )


def test_unrecognised_neighbour_text_is_not_an_empty_table() -> None:
    raw = "Welcome to the switch\nChassis id: aabb\n"

    assert classify_output(raw, platform="cisco_ios", command=commands.CMD_LLDP).status == (
        STATUS_NO_TEMPLATE
    )


def test_the_channel_commands_per_platform() -> None:
    assert commands.channel_command("cisco_ios") == "show etherchannel summary"
    assert commands.channel_command("cisco_xe") == "show etherchannel summary"
    assert commands.channel_command("cisco_nxos") == "show port-channel summary"
