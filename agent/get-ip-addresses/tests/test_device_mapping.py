import pytest

from manus_agent.csv_reader import read_csv_rows
from manus_agent.device_mapping import (
    map_interface,
    read_primary_flag,
    resolve_primary_ip,
    validate_mapping,
)
from tests.data_helpers import RAW_MAPPING


def rules():
    return validate_mapping(RAW_MAPPING)


def with_rows(*extra):
    return [*RAW_MAPPING, *extra]


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        (None, "list of"),
        ([], "list of"),
        (["x"], "must be an object"),
        ([{"source": "a", "target": "name", "x": 1}], "unknown key"),
        ([{"source": "", "target": "name"}], "source is empty"),
        ([{"source": "a", "target": "role.name"}], "unknown target"),
        ([{"source": "a", "target": "name"}, {"source": "b", "target": "name"}], "duplicate"),
        ([{"source": "a", "target": "interfaces.name"}], "'name' target"),
        ([{"source": "a", "target": "name"}], "interfaces.name"),
        (
            [
                {"source": "a", "target": "name"},
                {"source": "b", "target": "interfaces.name"},
                {"source": "c", "target": "_is_primary"},
            ],
            "primary flag",
        ),
        (
            [
                {"source": "a", "target": "name"},
                {"source": "b", "target": "interfaces.name"},
                {"source": "c", "target": "interfaces.ip_addresses.parent.namespace.name"},
            ],
            "namespace",
        ),
    ],
)
def test_invalid_mappings_are_refused(mapping, message):
    with pytest.raises(ValueError, match=message):
        validate_mapping(mapping)


def test_ignore_may_repeat_and_unmapped_columns_are_fine():
    parsed = validate_mapping(
        with_rows({"source": "x", "target": "_ignore"}, {"source": "y", "target": "_ignore"})
    )
    assert len(parsed) == len(RAW_MAPPING) + 2


def test_an_interface_line_is_nautobot_shaped():
    entry = {
        "name": "d",
        "interface_name": "eth0",
        "interface_address": "10.0.0.2/24",
        "namespace": "black",
    }
    assert map_interface(entry, rules()) == {
        "name": "eth0",
        "ip_addresses": [{"address": "10.0.0.2/24", "parent": {"namespace": {"name": "black"}}}],
    }


def test_a_line_without_an_interface_name_gives_no_interface():
    assert map_interface({"name": "d", "interface_address": "10.0.0.1/32"}, rules()) is None


@pytest.mark.parametrize(
    ("cell", "expected"),
    [("true", True), ("YES", True), ("1", True), ("false", False), ("", False), ("maybe", None)],
)
def test_primary_flag_values(cell, expected):
    assert read_primary_flag({"is_primary": cell}, rules()) is expected


def test_no_flag_column_means_not_primary():
    plain = validate_mapping(RAW_MAPPING[:4])
    assert read_primary_flag({"is_primary": "true"}, plain) is False


def iface(name, address, namespace=None):
    ip = {"address": address}
    if namespace:
        ip["parent"] = {"namespace": {"name": namespace}}
    return {"name": name, "ip_addresses": [ip]}


def test_one_flagged_interface_is_the_primary_ip_with_its_namespace():
    result = resolve_primary_ip([iface("eth0", "10.0.0.2/24", "black")])
    assert result.primary_ip4 == {
        "address": "10.0.0.2/24",
        "parent": {"namespace": {"name": "black"}},
    }
    assert result.problems == ()


def test_the_same_line_twice_is_still_one_primary():
    line = iface("eth0", "10.0.0.2/24")
    assert resolve_primary_ip([line, line]).primary_ip4 == {"address": "10.0.0.2/24"}


def test_two_different_primaries_are_a_problem_and_give_no_primary():
    result = resolve_primary_ip([iface("eth0", "10.0.0.2/24"), iface("eth1", "10.0.1.2/24")])
    assert result.primary_ip4 is None
    assert [p.code for p in result.problems] == ["multiple_primary_ip"]


def test_same_address_in_two_namespaces_counts_twice():
    result = resolve_primary_ip(
        [iface("eth0", "10.0.0.2/24", "a"), iface("eth0", "10.0.0.2/24", "b")]
    )
    assert [p.code for p in result.problems] == ["multiple_primary_ip"]


def test_a_flagged_line_without_an_address_is_a_problem():
    result = resolve_primary_ip([{"name": "eth0"}])
    assert result.primary_ip4 is None
    assert [p.code for p in result.problems] == ["primary_without_address"]


def test_no_flagged_line_is_no_primary_and_no_problem():
    result = resolve_primary_ip([])
    assert result.primary_ip4 is None
    assert result.problems == ()


def test_csv_reader_reports_ragged_and_empty_files(tmp_path):
    ragged = tmp_path / "a.csv"
    ragged.write_text("﻿a;b\n1\n2;3;4\n\n")
    rows, problems = read_csv_rows(ragged, ";")
    assert rows == [{"a": "1", "b": ""}, {"a": "2", "b": "3"}]
    assert len(problems) == 2
    empty = tmp_path / "b.csv"
    empty.write_text("\n\n")
    assert read_csv_rows(empty, ";")[1] == ["b.csv: file is empty (no header line)"]
    binary = tmp_path / "c.csv"
    binary.write_bytes(b"\xff\xfe\x00")
    assert "UTF-8" in read_csv_rows(binary, ";")[1][0]
    dup = tmp_path / "d.csv"
    dup.write_text("a;a\n1;2\n")
    assert "duplicate column" in read_csv_rows(dup, ";")[1][0]
