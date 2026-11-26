"""W3b-08: one reader of the CDP / LLDP neighbour columns for the two steps and Ask the Net.

``services/parsing/neighbors.neighbor_fields`` reads the TextFSM columns in one order (maintainer
decision 2026-11-27): name ``neighbor_name`` | ``neighbor``; remote port ``neighbor_port_id`` |
``neighbor_interface`` (on IOS LLDP ``neighbor_interface`` is the neighbour's port *description*);
address ``mgmt_address`` | ``management_ip`` | ``interface_ip``; a list column gives its first item.
Each reader keeps its own sanitising and status vocabulary. The Ask the Net reader already used
this order; the two steps change.
"""

from __future__ import annotations

import json
from typing import Any

from services.ai_assistant.neighbors import records as ask_the_net
from services.ai_assistant.neighbors.catalogue import Step
from workflow_steps.collect_client_data.parsing import parse_neighbors
from workflow_steps.discover_network.parsing import classify_cdp_output

# Shaped like ntc-templates cisco_ios_show_lldp_neighbors_detail (lower-cased keys).
_IOS_LLDP = {
    "local_interface": "Gi1/0/1",
    "neighbor_port_id": "Gi0/24",
    "neighbor_interface": "uplink to core",
    "neighbor_name": "sw2",
    "capabilities": "B,R",
    "mgmt_address": "10.0.0.2",
}
# Shaped like ntc-templates cisco_nxos_show_cdp_neighbors_detail.
_NXOS_CDP = {
    "neighbor_name": "nx2",
    "mgmt_address": "",
    "interface_ip": "10.0.0.9",
    "platform": "N9K-C93180YC-EX",
    "neighbor_interface": "Ethernet1/1",
    "local_interface": "Ethernet1/49",
    "neighbor_description": "NX-OS 10.2",
    "capabilities": "R S I",
}


def _discover(row: dict[str, Any]):
    (neighbor,) = classify_cdp_output(json.dumps([row])).neighbors
    return neighbor


# -- collect-client-data (Collect Client Data) ---------------------------------------------------


def test_collect_client_data_takes_the_lldp_port_id_not_the_description() -> None:
    (entry,) = parse_neighbors([_IOS_LLDP], "lldp", "cisco_ios")
    assert entry.neighbor_port == "Gi0/24"
    assert entry.neighbor_name == "sw2"


def test_collect_client_data_falls_back_to_neighbor_interface() -> None:
    row = {k: v for k, v in _IOS_LLDP.items() if k != "neighbor_port_id"}
    (entry,) = parse_neighbors([row], "lldp", "cisco_ios")
    assert entry.neighbor_port == "uplink to core"


def test_collect_client_data_reads_a_list_column_by_its_first_item() -> None:
    row = {**_IOS_LLDP, "neighbor_name": ["sw2", "sw2-b"], "capabilities": ["B,R"]}
    (entry,) = parse_neighbors([row], "lldp", "cisco_ios")
    assert entry.neighbor_name == "sw2"
    assert entry.capabilities == ("bridge", "router")


# -- discover-network (Discover Network) ---------------------------------------------------------


def test_discover_network_reads_the_nxos_interface_ip() -> None:
    neighbor = _discover(_NXOS_CDP)
    assert neighbor.ip == "10.0.0.9"
    assert (neighbor.local_port, neighbor.remote_port) == ("Ethernet1/49", "Ethernet1/1")
    assert neighbor.software == "NX-OS 10.2"


def test_discover_network_reads_list_columns_and_the_name_alias() -> None:
    row = {
        "neighbor": "r3",
        "mgmt_address": ["10.0.0.3", "10.0.0.33"],
        "local_interface": "Gi0/1",
        "neighbor_interface": "Gi0/2",
        "capabilities": "R",
    }
    neighbor = _discover(row)
    assert (neighbor.name, neighbor.ip) == ("r3", "10.0.0.3")


def test_discover_network_keeps_its_ipv4_only_rule() -> None:
    neighbor = _discover({**_NXOS_CDP, "interface_ip": "2001:db8::9"})
    assert neighbor.ip is None


# -- Ask the Net (unchanged: characterization) ---------------------------------------------------


def test_ask_the_net_reads_the_same_fields_as_before() -> None:
    records = ask_the_net.normalize_rows(
        Step(command="show lldp neighbors detail", layer="l2", protocol="lldp", vrf="default"),
        [_IOS_LLDP, _NXOS_CDP, {"neighbor": "x", "local_interface": "", "mgmt_address": "\x00"}],
    )
    assert [
        (r["neighbor_name"], r["neighbor_interface"], r["neighbor_ip"], r["local_interface"])
        for r in records
    ] == [
        ("sw2", "Gi0/24", "10.0.0.2", "Gi1/0/1"),
        ("nx2", "Ethernet1/1", "10.0.0.9", "Ethernet1/49"),
        ("x", "", None, ""),
    ]
    assert records[0]["capabilities"] == ["B", "R"]


def test_a_blank_column_falls_through_to_the_next_one() -> None:
    # whitespace and invisible characters count as blank, in every reader (Ask the Net did this
    # already; the steps now share it)
    row = {
        **_NXOS_CDP,
        "mgmt_address": " ​ ",
        "management_ip": "\x00",
        "neighbor_name": "  ",
        "neighbor": "nx2-alias",
    }
    neighbor = _discover(row)
    assert (neighbor.name, neighbor.ip) == ("nx2-alias", "10.0.0.9")
    (record,) = ask_the_net.normalize_rows(
        Step(command="show cdp neighbors detail", layer="l2", protocol="cdp", vrf="default"), [row]
    )
    assert (record["neighbor_name"], record["neighbor_ip"]) == ("nx2-alias", "10.0.0.9")
