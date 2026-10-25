import pytest

from manus_agent.device_mapping import validate_mapping
from manus_agent.ip_index import IndexLimitError, build_index, entry_to_answer
from tests.data_helpers import RAW_MAPPING, SAMPLE_CSV

RULES = validate_mapping(RAW_MAPPING)
HEADER = "name;interface_name;interface_address;is_primary;namespace\n"


def index_of(tmp_path, *contents):
    files = []
    for number, content in enumerate(contents):
        path = tmp_path / f"f{number}.csv"
        path.write_text(content)
        files.append(path)
    return build_index(files, ";", RULES)


def test_the_sample_gives_both_interfaces_and_the_primary_ip(tmp_path):
    index = index_of(tmp_path, SAMPLE_CSV)
    entry = index.lookup("device-1")
    assert [i["name"] for i in entry.interfaces] == ["eth0", "eth1"]
    assert entry.primary_ip4 == {
        "address": "10.0.0.2/24",
        "parent": {"namespace": {"name": "black"}},
    }
    assert (index.files_read, index.rows, index.warnings) == (1, 2, ())


def test_lookup_finds_an_unambiguous_name_ignoring_case_and_blanks(tmp_path):
    index = index_of(tmp_path, HEADER + "Core-SW1;eth0;10.0.0.1/32;true;Global\n")
    assert index.lookup("  core-sw1 ").name == "Core-SW1"
    assert index.lookup("Core-SW1").name == "Core-SW1"


def test_names_that_differ_only_in_case_are_two_devices(tmp_path):
    index = index_of(
        tmp_path,
        HEADER + "Core-SW1;eth0;10.0.0.1/32;true;Global\ncore-sw1;eth9;10.9.9.9/32;true;Global\n",
    )
    assert [i["name"] for i in index.lookup("Core-SW1").interfaces] == ["eth0"]
    assert [i["name"] for i in index.lookup("core-sw1").interfaces] == ["eth9"]
    # ambiguous without an exact match: no guess
    assert index.lookup("CORE-SW1") is None
    assert any("differ only in case" in w for w in index.warnings)


def test_unknown_device_is_none(tmp_path):
    assert index_of(tmp_path, SAMPLE_CSV).lookup("nope") is None


def test_lines_of_one_device_in_several_files_are_merged(tmp_path):
    index = index_of(
        tmp_path,
        HEADER + "d;eth0;10.0.0.1/24;true;Global\n",
        HEADER + "d;eth1;10.0.1.1/24;false;Global\nother;eth0;10.9.9.9/24;false;Global\n",
    )
    assert [i["name"] for i in index.lookup("d").interfaces] == ["eth0", "eth1"]
    assert len(index.devices) == 2


def test_two_primaries_give_a_problem_and_no_primary(tmp_path):
    index = index_of(
        tmp_path, HEADER + "d;eth0;10.0.0.1/24;true;Global\nd;eth1;10.0.1.1/24;true;Global\n"
    )
    entry = index.lookup("d")
    assert entry.primary_ip4 is None
    assert [p.code for p in entry.problems] == ["multiple_primary_ip"]
    assert "d: multiple_primary_ip" in index.warnings
    # the log gets the code, never interface names or addresses
    assert not any("10.0." in w or "eth" in w for w in index.warnings)
    assert "10.0.0.1/24" in entry.problems[0].message  # the caller still gets the details


def test_an_unreadable_flag_drops_the_primary_but_keeps_the_interfaces(tmp_path):
    index = index_of(tmp_path, HEADER + "d;eth0;10.0.0.1/24;maybe;Global\n")
    entry = index.lookup("d")
    assert entry.primary_ip4 is None
    assert entry.interfaces[0]["name"] == "eth0"
    assert [p.code for p in entry.problems] == ["invalid_primary_flag"]


def test_lines_without_a_device_name_are_counted_not_indexed(tmp_path):
    index = index_of(tmp_path, HEADER + ";eth0;10.0.0.1/24;true;Global\n")
    assert index.devices == {}
    assert "1 line(s) skipped" in index.warnings[0]


def test_one_device_with_many_lines_builds_in_linear_time(tmp_path):
    lines = "".join(f"big;e{n};10.{n // 250}.{n % 250}.1/24;false;Global\n" for n in range(20000))
    index = index_of(tmp_path, HEADER + lines)
    assert len(index.lookup("big").interfaces) == 20000


def test_the_total_size_and_line_limits_stop_the_build(tmp_path, monkeypatch):
    path = tmp_path / "a.csv"
    path.write_text(SAMPLE_CSV)
    monkeypatch.setattr("manus_agent.ip_index.MAX_TOTAL_BYTES", 10)
    with pytest.raises(IndexLimitError, match="above the limit"):
        build_index([path], ";", RULES)
    monkeypatch.setattr("manus_agent.ip_index.MAX_TOTAL_BYTES", 10**9)
    monkeypatch.setattr("manus_agent.ip_index.MAX_TOTAL_ROWS", 1)
    with pytest.raises(IndexLimitError, match="more than 1 lines"):
        build_index([path], ";", RULES)


def test_answers_are_copies_the_cache_cannot_be_changed_through(tmp_path):
    entry = index_of(tmp_path, SAMPLE_CSV).lookup("device-1")
    answer = entry_to_answer(entry)
    answer["interfaces"][0]["name"] = "changed"
    answer["primary_ip4"]["address"] = "changed"
    assert entry.interfaces[0]["name"] == "eth0"
    assert entry.primary_ip4["address"] == "10.0.0.2/24"


def test_an_answer_without_a_primary_has_no_primary_key(tmp_path):
    entry = index_of(tmp_path, HEADER + "d;eth0;10.0.0.1/24;false;Global\n").lookup("d")
    assert "primary_ip4" not in entry_to_answer(entry)
