"""Batfish edges as neighbour records (doc/AI_TOOL_CHAIN.md §24.14)."""

from __future__ import annotations

from services.ai_assistant.neighbors import model as nm


def test_endpoints_in_both_spellings() -> None:
    assert nm.parse_endpoint("r1[GigabitEthernet0/0]") == ("r1", "GigabitEthernet0/0")
    assert nm.parse_endpoint({"hostname": "r1", "interface": "Gi0/0"}) == ("r1", "Gi0/0")
    assert nm.parse_endpoint("garbage") == ("", "")
    assert nm.parse_endpoint(None) == ("", "")


def test_only_edges_starting_on_the_device_become_records() -> None:
    rows = [
        {
            "Interface": "R1[Gi0/0]",
            "IPs": ["10.0.0.1"],
            "Remote_Interface": "r2[Gi0/1]",
            "Remote_IPs": ["10.0.0.2"],
        },
        {
            "Interface": "r2[Gi0/1]",
            "IPs": ["10.0.0.2"],
            "Remote_Interface": "r1[Gi0/0]",
            "Remote_IPs": ["10.0.0.1"],
        },
        {"Interface": "r1[Gi0/5]", "IPs": [], "Remote_Interface": "x", "Remote_IPs": []},
    ]

    records = nm.edge_records(rows, "ospf", "r1")

    assert records == [
        {
            "layer": "l3",
            "protocol": "ospf",
            "source": "model",
            "interface": "Gi0/0",
            "ips": ["10.0.0.1"],
            "neighbor_name": "r2",
            "neighbor_interface": "Gi0/1",
            "neighbor_ips": ["10.0.0.2"],
        }
    ]
