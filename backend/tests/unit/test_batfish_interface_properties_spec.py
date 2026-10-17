"""INTERFACE_PROPERTIES_SPEC: node identity comes from the nested ``Interface.hostname``."""

from __future__ import annotations

from services.batfish.interface_properties_spec import INTERFACE_PROPERTIES_SPEC


def test_node_key_reads_the_nested_interface_hostname() -> None:
    row = {"Interface": {"hostname": "r1", "interface": "Gi0/1"}}
    assert INTERFACE_PROPERTIES_SPEC.node_key(row) == "r1"


def test_node_key_is_none_for_a_missing_or_malformed_interface() -> None:
    for row in ({}, {"Interface": None}, {"Interface": "r1[Gi0/1]"}):
        assert INTERFACE_PROPERTIES_SPEC.node_key(row) is None


def test_parsed_nests_each_interface_under_its_name() -> None:
    rows = [
        {"Interface": {"hostname": "r1", "interface": "Gi0/1"}, "Active": True},
        {"Interface": {"hostname": "r1", "interface": "Gi0/2"}, "Active": False},
        {"Interface": {"hostname": "r1", "interface": ""}, "Active": True},
    ]
    parsed = INTERFACE_PROPERTIES_SPEC.build_parsed_for_node(rows)
    assert parsed == {"Interfaces": {"Gi0/1": {"Active": True}, "Gi0/2": {"Active": False}}}
