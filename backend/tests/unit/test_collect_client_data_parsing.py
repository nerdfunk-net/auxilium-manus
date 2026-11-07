"""Tests for the pure parsing helpers of the collect-client-data step."""

from __future__ import annotations

import json

import pytest

from workflow_steps.collect_client_data.parsing import (
    STATUS_NO_TEMPLATE,
    STATUS_NOT_SUPPORTED,
    STATUS_OK,
    ArpEntry,
    MacEntry,
    classify_output,
    normalise_mac,
    parse_arp,
    parse_mac_table,
    parse_vrf_names,
    svi_vlan,
)

IOS_ARP_HEADER_ONLY = "Protocol  Address          Age (min)  Hardware Addr   Type   Interface\n"
IOS_REFUSAL = "                ^\n% Invalid input detected at '^' marker.\n"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("aabb.ccdd.eeff", "aabb.ccdd.eeff"),
        ("AABB.CCDD.EEFF", "aabb.ccdd.eeff"),
        ("aa:bb:cc:dd:ee:ff", "aabb.ccdd.eeff"),
        ("AA-BB-CC-DD-EE-FF", "aabb.ccdd.eeff"),
        ("aabbccddeeff", "aabb.ccdd.eeff"),
        ("  aabb.ccdd.eeff \n", "aabb.ccdd.eeff"),
    ],
)
def test_normalise_mac_accepts_common_formats(raw: str, expected: str) -> None:
    assert normalise_mac(raw) == expected


@pytest.mark.parametrize(
    "raw", [None, "", "Incomplete", "aabb.ccdd", "gggg.hhhh.iiii", "aabb.ccdd.eeff.0011"]
)
def test_normalise_mac_rejects_invalid_values(raw: str | None) -> None:
    assert normalise_mac(raw) is None


@pytest.mark.parametrize(
    ("interface", "vlan"),
    [
        ("Vlan10", "10"),
        ("vlan4094", "4094"),
        ("Vl20", "20"),
        ("GigabitEthernet0/1", None),
        ("Vlan10.5", None),
        ("Port-channel1", None),
        ("", None),
        (None, None),
    ],
)
def test_svi_vlan(interface: str | None, vlan: str | None) -> None:
    assert svi_vlan(interface) == vlan


def test_parse_arp_default_vrf_sets_vlan_from_svi() -> None:
    rows = [
        {
            "protocol": "Internet",
            "ip_address": "10.0.10.5",
            "age": "3",
            "mac_address": "AABB.CCDD.EEFF",
            "type": "ARPA",
            "interface": "Vlan10",
        }
    ]
    assert parse_arp(rows, vrf=None) == [
        ArpEntry(
            ip_address="10.0.10.5",
            mac_address="aabb.ccdd.eeff",
            interface="Vlan10",
            vrf=None,
            vlan="10",
        )
    ]


def test_parse_arp_keeps_vrf_and_routed_port_without_vlan() -> None:
    rows = [{"ip_address": "192.0.2.1", "mac_address": "aabb.ccdd.0001", "interface": "Gi0/0/1"}]
    (entry,) = parse_arp(rows, vrf="CUSTOMER")
    assert entry.vrf == "CUSTOMER"
    assert entry.interface == "Gi0/0/1"
    assert entry.vlan is None


def test_parse_arp_incomplete_mac_is_kept_without_mac() -> None:
    rows = [{"ip_address": "10.0.0.9", "mac_address": "Incomplete", "interface": "Vlan10"}]
    (entry,) = parse_arp(rows, vrf=None)
    assert entry.ip_address == "10.0.0.9"
    assert entry.mac_address is None


def test_parse_arp_skips_rows_without_a_valid_ip() -> None:
    rows = [
        {"ip_address": "", "mac_address": "aabb.ccdd.eeff"},
        {"ip_address": "not-an-ip", "mac_address": "aabb.ccdd.eeff"},
        {"mac_address": "aabb.ccdd.eeff"},
    ]
    assert parse_arp(rows, vrf=None) == []


def test_parse_mac_table_ios_list_port_and_vlan_id() -> None:
    rows = [
        {
            "destination_address": "AABB.CCDD.EEFF",
            "type": "DYNAMIC",
            "vlan_id": "20",
            "destination_port": ["Gi1/0/5"],
        }
    ]
    assert parse_mac_table(rows) == [
        MacEntry(mac_address="aabb.ccdd.eeff", vlan="20", port="Gi1/0/5")
    ]


def test_parse_mac_table_nxos_string_ports() -> None:
    rows = [{"vlan_id": "*   30", "mac_address": "aabb.ccdd.0002", "ports": "Eth1/7"}]
    (entry,) = parse_mac_table(rows)
    assert entry.mac_address == "aabb.ccdd.0002"
    assert entry.port == "Eth1/7"
    assert entry.vlan == "30"


def test_parse_mac_table_skips_invalid_mac_and_handles_missing_port() -> None:
    rows = [
        {"destination_address": "", "vlan_id": "1", "destination_port": ["Gi1/0/1"]},
        {"destination_address": "aabb.ccdd.0003", "vlan_id": "1", "destination_port": []},
    ]
    (entry,) = parse_mac_table(rows)
    assert entry.mac_address == "aabb.ccdd.0003"
    assert entry.port is None


def test_parse_vrf_names_from_textfsm_list_skips_default_and_duplicates() -> None:
    output = json.dumps(
        [{"name": "default"}, {"name": "CUSTOMER"}, {"name": "mgmt"}, {"name": "CUSTOMER"}]
    )
    assert parse_vrf_names(output) == ["CUSTOMER", "mgmt"]


def test_parse_vrf_names_raw_text_fallback() -> None:
    output = (
        "  Name                             Default RD            Interfaces\n"
        "  CUSTOMER                         65000:1               Gi0/0/1\n"
        "  MGMT                             <not set>             Gi0/0/0\n"
    )
    assert parse_vrf_names(output) == ["CUSTOMER", "MGMT"]


@pytest.mark.parametrize("output", ["", "   \n", "[]", IOS_REFUSAL])
def test_parse_vrf_names_without_vrfs_or_on_refusal(output: str) -> None:
    assert parse_vrf_names(output) == []


def test_classify_json_list_is_ok_with_rows() -> None:
    raw = json.dumps([{"ip_address": "10.0.0.1"}])
    result = classify_output(raw, platform="cisco_ios", command="show ip arp")
    assert result.status == STATUS_OK
    assert result.rows == [{"ip_address": "10.0.0.1"}]


@pytest.mark.parametrize("command", ["show vrf", "show ip arp vrf vrf-1"])
def test_classify_blank_output_is_empty_only_where_a_device_prints_nothing(command: str) -> None:
    # A device with no VRF, or an empty VRF, prints nothing at all.
    result = classify_output("", platform="cisco_ios", command=command)
    assert (result.status, result.rows) == (STATUS_OK, [])


@pytest.mark.parametrize("command", ["show ip arp", "show mac address-table"])
def test_classify_blank_default_table_is_not_a_table(command: str) -> None:
    # The default tables always print a header; blank means a dropped session, not "no rows".
    assert classify_output("  \n", platform="cisco_ios", command=command).status == (
        STATUS_NO_TEMPLATE
    )


def test_classify_cli_refusal_is_not_supported() -> None:
    result = classify_output(IOS_REFUSAL, platform="cisco_ios", command="show mac address-table")
    assert result.status == STATUS_NOT_SUPPORTED
    assert result.rows == []


def test_classify_header_only_table_with_template_is_ok_empty() -> None:
    # Netmiko returns the raw text when TextFSM finds a template but zero rows.
    result = classify_output(IOS_ARP_HEADER_ONLY, platform="cisco_ios", command="show ip arp")
    assert (result.status, result.rows) == (STATUS_OK, [])


def test_classify_unknown_platform_is_no_template() -> None:
    result = classify_output("some text\n", platform="no_such_os", command="show ip arp")
    assert result.status == STATUS_NO_TEMPLATE
    assert result.rows == []


def test_classify_xe_falls_back_to_ios_templates() -> None:
    result = classify_output(IOS_ARP_HEADER_ONLY, platform="cisco_xe", command="show ip arp")
    assert result.status == STATUS_OK


def test_classify_json_that_is_not_a_list_is_no_template() -> None:
    result = classify_output('{"a": 1}', platform="cisco_ios", command="show ip arp")
    assert result.status == STATUS_NO_TEMPLATE


def test_parse_vrf_names_drops_names_that_are_unsafe_in_a_command() -> None:
    # VRF names come from device output and are put into "show ip arp vrf <name>".
    output = json.dumps(
        [
            {"name": "CUST-A_1.x"},
            {"name": "bad name"},
            {"name": "a;reload"},
            {"name": "x|include password"},
            {"name": "-leading"},
            {"name": "v" * 65},
        ]
    )
    assert parse_vrf_names(output) == ["CUST-A_1.x"]


@pytest.mark.parametrize("platform", ["cisco_ios", "cisco_xe", "cisco_nxos"])
@pytest.mark.parametrize("command", ["show ip arp", "show mac address-table"])
def test_unrecognised_text_is_never_an_empty_table(platform: str, command: str) -> None:
    # A banner, a pager glitch or an unprefixed authorization error must not look like
    # "zero entries": that would replace the device's good data with an empty collection.
    for text in ("garbage banner\n", "Authorization failed\n", "Connection closed\n"):
        result = classify_output(text, platform=platform, command=command)
        assert result.status == STATUS_NO_TEMPLATE, (platform, command, text)


def test_header_only_mac_table_is_an_empty_table() -> None:
    text = (
        "          Mac Address Table\n"
        "-------------------------------------------\n\n"
        "Vlan    Mac Address       Type        Ports\n"
        "----    -----------       --------    -----\n"
        "Total Mac Addresses for this criterion: 0\n"
    )
    result = classify_output(text, platform="cisco_ios", command="show mac address-table")
    assert (result.status, result.rows) == (STATUS_OK, [])


def test_vrf_text_fallback_ignores_continuation_lines() -> None:
    output = (
        "  Name                             Default RD            Protocols   Interfaces\n"
        "  CUSTOMER                         65000:1               ipv4        Gi0/0/1\n"
        "                                                                     Lo100\n"
        "  Lo0\n"
    )
    assert parse_vrf_names(output) == ["CUSTOMER"]


def test_nxos_arp_table_with_entries_that_textfsm_did_not_parse_is_not_empty() -> None:
    # Netmiko returns the raw text when the template yields no records; entries must not be
    # mistaken for "header and no entries".
    text = (
        "IP ARP Table for context default\nTotal number of entries: 1\n"
        "IP Address       Age       MAC Address     Interface       Flags\n"
        "10.0.0.5         00:01:00  aabb.ccdd.0001  Vlan10\n"
    )
    result = classify_output(text, platform="cisco_nxos", command="show ip arp")
    assert result.status == STATUS_NO_TEMPLATE


def test_mac_table_with_entries_that_textfsm_did_not_parse_is_not_empty() -> None:
    text = (
        "Vlan    Mac Address       Type        Ports\n"
        "10      aabb.ccdd.0001    DYNAMIC     Gi1/0/1\n"
    )
    result = classify_output(text, platform="cisco_ios", command="show mac address-table")
    assert result.status == STATUS_NO_TEMPLATE
