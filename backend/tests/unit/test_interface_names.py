"""Interface-name canonicalisation (doc/AI_TOOL_CHAIN.md §24.14)."""

from __future__ import annotations

import pytest

from services.network.interface_names import canonical_interface_name, same_interface


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Gig 1/0/1", "GigabitEthernet1/0/1"),
        ("Gi1/0/1", "GigabitEthernet1/0/1"),
        ("gigabitethernet1/0/1", "GigabitEthernet1/0/1"),
        ("GigabitEthernet1/0/1", "GigabitEthernet1/0/1"),
        ("Fas 0/1", "FastEthernet0/1"),
        ("Fa0/1", "FastEthernet0/1"),
        ("Ten 1/1/1", "TenGigabitEthernet1/1/1"),
        ("Te1/1/1", "TenGigabitEthernet1/1/1"),
        ("Twe1/0/1", "TwentyFiveGigE1/0/1"),
        ("Fo1/1/1", "FortyGigabitEthernet1/1/1"),
        ("Hu1/0/1", "HundredGigE1/0/1"),
        ("Eth1/1", "Ethernet1/1"),
        ("Ethernet1/1", "Ethernet1/1"),
        ("Po1", "Port-channel1"),
        ("port-channel 10", "Port-channel10"),
        ("Lo0", "Loopback0"),
        ("Vl100", "Vlan100"),
        ("Gi0/0/0/1", "GigabitEthernet0/0/0/1"),
        ("  Gi1/0/1.100 ", "GigabitEthernet1/0/1.100"),
        ("mgmt0", "mgmt0"),
        ("ge-0/0/1", "ge-0/0/1"),
    ],
)
def test_canonical_interface_name(raw: str, expected: str) -> None:
    assert canonical_interface_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "Management"])
def test_unknown_or_empty_names_are_kept_trimmed(raw: str) -> None:
    assert canonical_interface_name(raw) == raw.strip()


def test_same_interface_compares_canonical_forms() -> None:
    assert same_interface("Gig 1/0/1", "GigabitEthernet1/0/1")
    assert same_interface("Eth1/1", "ethernet1/1")
    assert not same_interface("Gi1/0/1", "Gi1/0/2")
    assert not same_interface("", "")
