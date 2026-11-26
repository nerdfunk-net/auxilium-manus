"""W2-12 / W4-09: the interface payload builders and the config-to-attributes mappers share their
pieces instead of repeating them.

``config-to-attributes`` (Config to Attributes) maps five sources to Nautobot interfaces; each
mapper starts with the same fields and parses MTU and VLAN values. ``add-to-nautobot`` (Add to
Nautobot) and ``update-nautobot-device`` (Update Device) read interfaces from the Nautobot bag.
"""

from __future__ import annotations

import pytest

from workflow_steps.common.interface_payload import interfaces_from_nautobot_bag

# --- W2-12: interfaces_from_nautobot_bag (characterization: the same result before and after) --

_BAG = {
    "interfaces": [
        "not a dict",
        {"name": "  "},
        {
            "name": " Gi1/0/1 ",
            "type": "1000base-t",
            "description": " uplink ",
            "status": {"name": "Active"},
            "enabled": True,
            "mac_address": "aa:bb:cc:00:01:00",
            "mtu": "1500",
            "untagged_vlan": 10,
            "tagged_vlans": [20, None, "", "none", "vlan-uuid"],
            "lag": "Port-channel10",
            "ip_addresses": [
                {"address": "10.0.0.1/24", "ip_role": "none", "is_primary": True},
                {
                    "address": "10.0.0.2",
                    "ip_role": "secondary",
                    "parent": {"namespace": {"name": "Lab"}},
                },
                "10.0.0.3",
                {"address": " "},
            ],
            "interface_redundancy_groups": [
                {"protocol": "HSRP", "protocol_group_id": 1, "virtual_ip": "10.0.0.254"}
            ],
        },
        {
            "name": "Vlan20",
            "status": "Planned",
            "enabled": "yes",
            "untagged_vlan": "none",
            "lag": "none",
            "tagged_vlans": ["none"],
            "ip_addresses": [],
        },
    ]
}

_EXPECTED = [
    {
        "name": "Gi1/0/1",
        "type": "1000base-t",
        "description": "uplink",
        "status": "Active",
        "enabled": True,
        "mac_address": "AA:BB:CC:00:01:00",
        "mtu": 1500,
        "untagged_vlan": 10,
        "lag": "Port-channel10",
        "tagged_vlans": [20, "vlan-uuid"],
        "ip_addresses": [
            {"address": "10.0.0.1/24", "namespace": "Global", "is_primary": True},
            {"address": "10.0.0.2/32", "namespace": "Lab", "ip_role": "secondary"},
            {"address": "10.0.0.3/32", "namespace": "Global"},
        ],
        "interface_redundancy_groups": [
            {
                "protocol": "hsrp",
                "protocol_group_id": "1",
                "virtual_ip": {"address": "10.0.0.254"},
                "namespace": "Global",
            }
        ],
    },
    {"name": "Vlan20", "status": "Planned"},
]


def test_the_bag_builder_keeps_its_output() -> None:
    assert interfaces_from_nautobot_bag(_BAG, default_prefix_length="32") == _EXPECTED


@pytest.mark.parametrize("bag", [None, {}, {"interfaces": "x"}, []])
def test_a_bag_without_an_interface_list_has_no_interfaces(bag) -> None:
    assert interfaces_from_nautobot_bag(bag, default_prefix_length="/24") == []


def test_the_prefix_length_is_given_with_or_without_its_slash() -> None:
    bag = {"interfaces": [{"name": "e0", "ip_addresses": ["10.1.1.1"]}]}

    for length in ("/24", "24"):
        (iface,) = interfaces_from_nautobot_bag(bag, default_prefix_length=length)
        assert iface["ip_addresses"][0]["address"] == "10.1.1.1/24"


def test_the_redundancy_settings_live_with_the_redundancy_reader() -> None:
    import importlib.util

    from workflow_steps.common import redundancy_groups

    assert importlib.util.find_spec("workflow_steps.common.redundancy_groups_config") is None
    assert redundancy_groups.default_redundancy_groups()["enabled"] is False
    assert redundancy_groups.parse_redundancy_groups({}, step_id="s", interfaces_source="x") == (
        None,
        "Active",
    )


# --- W4-09: one interface preamble, one MTU guard, one VLAN id parser ----------------------------


def test_base_interface_is_the_shared_preamble() -> None:
    from workflow_steps.config_to_attributes.mapper_common import base_interface

    assert base_interface("Gi1/0/1", enabled=False, description="  core ") == {
        "name": "Gi1/0/1",
        "status": "Active",
        "type": "1000base-t",
        "enabled": False,
        "description": "core",
    }
    assert "description" not in base_interface("Loopback0", enabled=True, description=" ")
    assert "description" not in base_interface("Loopback0", enabled=True, description=None)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1500, 1500), (9216.0, 9216), ("1500", None), (0, None), (-1, None), (True, None),
     (1500.5, None), (None, None)],
)  # fmt: skip
def test_positive_int_is_the_one_mtu_guard(value, expected) -> None:
    from workflow_steps.config_to_attributes.mapper_common import positive_int

    assert positive_int(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(10, 10), ("10", 10), (" 20 ", 20), (4094, 4094), (0, None), (4095, None), ("x", None),
     (True, None), (None, None), ("", None), (-5, None), ("1.5", None)],
)  # fmt: skip
def test_vlan_id_is_the_one_scalar_vlan_parser(value, expected) -> None:
    from workflow_steps.config_to_attributes.mapper_common import vlan_id

    assert vlan_id(value) == expected


def test_batfish_drops_an_mtu_that_is_not_a_positive_integer() -> None:
    from workflow_steps.config_to_attributes.batfish_facts import _build_interface

    assert "mtu" not in _build_interface("Gi1", {"MTU": True})
    assert "mtu" not in _build_interface("Gi1", {"MTU": -1})
    assert _build_interface("Gi1", {"MTU": 1500})["mtu"] == 1500


def test_batfish_and_catalyst_drop_a_vlan_outside_1_to_4094() -> None:
    from workflow_steps.config_to_attributes.batfish_facts import _build_interface as batfish
    from workflow_steps.config_to_attributes.catalyst_details import _build_interface as catalyst

    access = {"Switchport_Mode": "ACCESS", "Access_VLAN": 5000}
    assert "untagged_vlan" not in batfish("Gi1", access)
    assert batfish("Gi1", {**access, "Access_VLAN": 30})["untagged_vlan"] == 30
    raw = {"name": "Gi1", "port_mode": "access", "vlan_id": "5000"}
    assert "untagged_vlan" not in catalyst(raw)
    assert catalyst({**raw, "vlan_id": "30"})["untagged_vlan"] == 30


def test_genie_drops_an_access_vlan_outside_1_to_4094() -> None:
    from workflow_steps.config_to_attributes.genie_running_config import _build_interface

    assert "untagged_vlan" not in _build_interface("Gi1", {"switchport access vlan 5000": {}})
    assert _build_interface("Gi1", {"switchport access vlan 30": {}})["untagged_vlan"] == 30
