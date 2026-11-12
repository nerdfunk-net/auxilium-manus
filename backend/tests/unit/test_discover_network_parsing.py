"""CDP detail parsing, platform guessing and text sanitising of the discover-network step."""

from __future__ import annotations

import json

import pytest

from workflow_steps.discover_network.parsing import (
    CDP_COMMAND,
    CdpStatus,
    classify_cdp_output,
    device_type_from_platform,
    neighbor_device_type,
    sanitize_text,
)


def _row(**over: str) -> dict[str, str]:
    base = {
        "neighbor_name": "sw2.example.com",
        "mgmt_address": "10.1.0.2",
        "platform": "cisco WS-C3850-48P",
        "local_interface": "GigabitEthernet1/0/1",
        "neighbor_interface": "GigabitEthernet1/0/48",
        "capabilities": "Router Switch IGMP",
    }
    return {**base, **over}


def test_parses_a_cdp_detail_row() -> None:
    result = classify_cdp_output(json.dumps([_row()]))
    assert result.status is CdpStatus.OK
    (n,) = result.neighbors
    assert n.name == "sw2.example.com"
    assert n.ip == "10.1.0.2"
    assert n.platform == "cisco WS-C3850-48P"
    assert n.local_port == "GigabitEthernet1/0/1"
    assert n.remote_port == "GigabitEthernet1/0/48"
    assert n.capabilities == ("bridge", "router")
    assert n.is_infrastructure


def test_missing_or_non_ip_management_address_gives_no_ip() -> None:
    rows = [_row(mgmt_address=""), _row(mgmt_address="0a01.0203"), _row(mgmt_address="999.1.1.1")]
    result = classify_cdp_output(json.dumps(rows))
    assert [n.ip for n in result.neighbors] == [None, None, None]


def test_a_phone_is_not_infrastructure() -> None:
    result = classify_cdp_output(json.dumps([_row(capabilities="Host Phone")]))
    assert not result.neighbors[0].is_infrastructure


def test_rows_without_a_name_are_skipped() -> None:
    result = classify_cdp_output(json.dumps([_row(neighbor_name=""), _row()]))
    assert len(result.neighbors) == 1


def test_zero_entries_is_an_empty_table() -> None:
    raw = "Total cdp entries displayed : 0\n"
    result = classify_cdp_output(raw)
    assert result.status is CdpStatus.OK
    assert result.neighbors == ()


def test_cdp_switched_off_is_reported() -> None:
    assert classify_cdp_output("% CDP is not enabled\n").status is CdpStatus.NOT_ENABLED


@pytest.mark.parametrize("raw", ["", "   \n", "garbage banner text", "{}", "[1, 2]"])
def test_blank_or_unparseable_output_is_not_trusted(raw: str) -> None:
    result = classify_cdp_output(raw)
    assert result.status is CdpStatus.UNPARSEABLE
    assert result.neighbors == ()


def test_cli_refusal_is_not_supported() -> None:
    raw = "% Invalid input detected at '^' marker.\n"
    assert classify_cdp_output(raw).status is CdpStatus.NOT_SUPPORTED


def test_command_is_the_detail_form() -> None:
    assert CDP_COMMAND == "show cdp neighbors detail"


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("cisco WS-C3850-48P", "cisco_ios"),
        ("cisco WS-C2960X-48FPD-L", "cisco_ios"),
        ("cisco C9300-48P", "cisco_xe"),
        ("Cisco ISR4331/K9", "cisco_xe"),
        ("cisco CSR1000V", "cisco_xe"),
        ("cisco Nexus9000 C93180YC-EX Chassis", "cisco_nxos"),
        ("N9K-C9336C-FX2", "cisco_nxos"),
        ("cisco N5K-C5548UP", "cisco_nxos"),
        ("Linux", None),
        ("Juniper EX4300", None),
        ("cisco AIR-AP2802I-E-K9", None),
        ("cisco IP Phone 8851", None),
        # CDP platform strings without the vendor word (finding 6 of the review)
        ("WS-C2960-24TT-L", "cisco_ios"),
        ("WS-C3750X-48P", "cisco_ios"),
        ("Catalyst 2960", "cisco_ios"),
        ("Catalyst 9300", "cisco_xe"),
        ("ISR4331/K9", "cisco_xe"),
        ("AIR-AP2802I-E-K9", None),
        ("Juniper EX4300", None),
    ],
)
def test_platform_string_to_device_type(platform: str, expected: str | None) -> None:
    assert device_type_from_platform(platform, override=None) == expected


def test_override_applies_only_when_no_platform_string_was_reported() -> None:
    assert device_type_from_platform("", override="cisco_xe") == "cisco_xe"
    assert device_type_from_platform(None, override="cisco_nxos") == "cisco_nxos"
    assert device_type_from_platform("Linux", override="cisco_xe") is None
    assert device_type_from_platform("", override=None) is None
    # An override that names an unsupported driver is ignored, never passed on.
    assert device_type_from_platform("", override="juniper_junos") is None


def test_sanitize_strips_control_characters_and_cuts() -> None:
    assert sanitize_text("sw\x00\x1b[31m1\n") == "sw[31m1"
    assert len(sanitize_text("a" * 500)) == 100
    assert sanitize_text(None) == ""


IOSXE_VM = (
    "Cisco IOS Software [IOSXE], Linux Software (X86_64BI_LINUX_L2-ADVENTERPRISEK9-M), "
    "Version 17.15.1, RELEASE SOFTWARE (fc4)"
)
IOL = (
    "Cisco IOS Software, Linux Software (I86BI_LINUX-ADVENTERPRISEK9-M), "
    "Version 15.2(4)M, RELEASE SOFTWARE"
)


def _neighbor(platform: str, software: str = ""):  # noqa: ANN202
    result = classify_cdp_output(
        json.dumps([_row(platform=platform, neighbor_description=software)])
    )
    return result.neighbors[0]


def test_the_software_line_of_the_detail_output_is_kept() -> None:
    assert _neighbor("Linux Unix", IOSXE_VM).software == IOSXE_VM
    assert _neighbor("Linux Unix").software == ""
    assert len(_neighbor("x", "a" * 500).software) == 200


@pytest.mark.parametrize(
    ("platform", "software", "expected"),
    [
        # A virtual switch: the platform says Linux, the software line says IOS-XE / IOS.
        ("Linux Unix", IOSXE_VM, "cisco_xe"),
        ("Linux", IOL, "cisco_ios"),
        ("", "Cisco Nexus Operating System (NX-OS) Software, Version 9.3(8)", "cisco_nxos"),
        ("Linux Unix", "Cisco IOS XE Software, Version 17.9.4", "cisco_xe"),
        # Not supported whatever the vendor word says
        ("Linux Unix", "Cisco IOS XR Software (Cisco IOS-XRv 9000), Version 7.9.1", None),
        # Guard: an XR marker next to the IOS wording must never be read as IOS
        ("Linux", "Cisco IOS Software, IOS-XRv 9000 Version 7.9.1", None),
        ("Linux", "Linux version 5.4.0-100-generic", None),
        ("Linux", "", None),
        # The platform string wins when it is already usable
        ("cisco WS-C3850-48P", "Cisco IOS Software [IOSXE], Version 16.9", "cisco_ios"),
    ],
)
def test_the_software_line_is_the_fallback_when_the_platform_is_not_usable(
    platform: str, software: str, expected: str | None
) -> None:
    assert neighbor_device_type(_neighbor(platform, software), override=None) == expected


def test_software_wins_over_the_override_and_the_override_still_needs_an_empty_platform() -> None:
    assert neighbor_device_type(_neighbor("", IOSXE_VM), override="cisco_nxos") == "cisco_xe"
    assert neighbor_device_type(_neighbor("", ""), override="cisco_nxos") == "cisco_nxos"
    assert neighbor_device_type(_neighbor("Linux", ""), override="cisco_nxos") is None


RAW_VIRTUAL_SWITCH = f"""-------------------------
Device ID: sw-vios.lab
Entry address(es):
  IP address: 10.1.0.7
Platform: Linux Unix,  Capabilities: Router Switch IGMP
Interface: Ethernet0/1,  Port ID (outgoing port): Ethernet0/2
Holdtime : 130 sec

Version :
{IOSXE_VM}
Technical Support: http://www.cisco.com/techsupport

advertisement version: 2
Management address(es):
  IP address: 10.1.0.7

Total cdp entries displayed : 1
"""


def test_a_virtual_switch_through_the_real_textfsm_template() -> None:
    # Pins the template's field name for the software line (neighbor_description) and the
    # whole path: raw device text -> ntc-templates -> rows -> driver decision.
    from ntc_templates.parse import parse_output

    rows = parse_output(
        platform="cisco_ios", command="show cdp neighbors detail", data=RAW_VIRTUAL_SWITCH
    )
    (neighbor,) = classify_cdp_output(json.dumps(rows)).neighbors
    assert neighbor.platform == "Linux Unix"
    assert neighbor.software == IOSXE_VM
    assert device_type_from_platform(neighbor.platform, override=None) is None
    assert neighbor_device_type(neighbor, override=None) == "cisco_xe"
