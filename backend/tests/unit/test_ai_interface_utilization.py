"""``summarize_interface_utilization``: traffic rate against capacity from ``show interfaces``.

doc/AI_TOOL_CHAIN.md §56.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from services.ai_assistant import interface_utilization as iu
from services.ai_assistant.data_sharing import DataClass, SharingPolicy
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore, StoredResult
from services.ai_assistant.tools import interface_utilization_tools as iut
from services.ai_assistant.tools.base import ToolContext
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

USER = 4
CDP = "show cdp neighbors"


def row(name: str, **values: str) -> dict[str, Any]:
    """An IOS template row (strings): 1 Gbit/s link, 5 min rates in bits per second."""
    base = {
        "_command": "show interfaces",
        "interface": name,
        "link_status": "up",
        "protocol_status": "up",
        "description": "",
        "bandwidth": "1000000 Kbit",
        "speed": "1000Mb/s",
        "input_rate": "0",
        "output_rate": "0",
        "input_pps": "0",
        "output_pps": "0",
    }
    return {**base, **values}


def neighbor(local: str, name: str = "sw2.lab", **values: str) -> dict[str, Any]:
    base = {
        "_command": CDP,
        "neighbor_name": name,
        "local_interface": local,
        "platform": "WS-C3850",
        "capabilities": "R S I",
        "neighbor_interface": "Gig 1/0/48",
    }
    return {**base, **values}


# -- units -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "default", "expected"),
    [
        ("1000000 Kbit", "k", 1_000_000_000),
        ("1000000 Kbit/sec", "k", 1_000_000_000),
        ("10 Gbit", "k", 10_000_000_000),
        ("100 Mbit", "k", 100_000_000),
        ("1000Mb/s", "m", 1_000_000_000),
        ("5000000", "", 5_000_000),
        (" 42 ", "", 42),
        ("30000 bits/sec", "", 30_000),
        ("", "", None),
        (None, "", None),
        ("auto speed", "", None),
        ("-5", "", None),
    ],
)
def test_a_rate_or_capacity_in_bits_per_second(text: Any, default: str, expected: Any) -> None:
    assert iu.parse_bps(text, default_prefix=default) == expected


@pytest.mark.parametrize(
    ("bps", "text"),
    [(0, "0 bit/s"), (950, "950 bit/s"), (1_500_000, "1.5 Mbit/s"), (2_000_000_000, "2 Gbit/s")],
)
def test_a_rate_is_shown_in_a_readable_unit(bps: int, text: str) -> None:
    assert iu.format_bps(bps) == text


# -- one interface -----------------------------------------------------------------------------


def test_utilization_is_the_rate_over_the_capacity_per_direction() -> None:
    rows = [row("GigabitEthernet0/1", input_rate="250000000", output_rate="500000000")]

    (finding,) = iu.summarize_utilization(rows).findings

    assert finding["utilization_in_percent"] == 25.0
    assert finding["utilization_out_percent"] == 50.0
    assert finding["peak_percent"] == 50.0
    assert finding["rate_in"] == "250 Mbit/s"
    assert finding["capacity"] == "1 Gbit/s"


def test_an_empty_rate_is_not_reported_as_zero() -> None:
    rows = [row("Gi0/1", input_rate="", output_rate="")]

    summary = iu.summarize_utilization(rows)

    (finding,) = summary.findings
    assert finding["utilization_in_percent"] is None
    assert finding["peak_percent"] is None
    assert summary.interfaces_without_rates == 1


def test_capacity_falls_back_to_speed_and_then_to_unknown() -> None:
    fallback = row("Gi0/1", bandwidth="", input_rate="500000000")
    unknown = row("Gi0/2", bandwidth="", speed="auto speed", input_rate="500000000")

    summary = iu.summarize_utilization([fallback, unknown])

    by_name = {f["interface"]: f for f in summary.findings}
    assert by_name["Gi0/1"]["utilization_in_percent"] == 50.0
    assert by_name["Gi0/2"]["utilization_in_percent"] is None
    assert by_name["Gi0/2"]["rate_in"] == "500 Mbit/s"  # the rate is still given
    assert summary.interfaces_without_capacity == 1


def test_nxos_column_names_are_read() -> None:
    nx = {
        "_command": "show interface",
        "interface": "Ethernet1/1",
        "link_status": "up",
        "bandwidth": "10000000 Kbit",
        "bandwidth_input_rate": "1000000000",
        "bandwidth_output_rate": "2000000000",
    }

    (finding,) = iu.summarize_utilization([nx]).findings

    assert finding["utilization_in_percent"] == 10.0
    assert finding["utilization_out_percent"] == 20.0


def test_the_percentage_is_not_capped_at_one_hundred() -> None:
    (finding,) = iu.summarize_utilization([row("Gi0/1", input_rate="1500000000")]).findings

    assert finding["utilization_in_percent"] == 150.0  # a wrong BW is visible, not hidden


# -- many interfaces ---------------------------------------------------------------------------


def test_interfaces_are_sorted_by_the_busier_direction() -> None:
    rows = [
        row("Gi0/1", input_rate="100000000"),
        row("Gi0/2", output_rate="900000000"),
        row("Gi0/3", input_rate="500000000", output_rate="10"),
    ]

    summary = iu.summarize_utilization(rows)

    assert [f["interface"] for f in summary.findings] == ["Gi0/2", "Gi0/3", "Gi0/1"]
    assert summary.busiest == {"interface": "Gi0/2", "percent": 90.0, "by": "peak_percent"}


def test_sort_by_input_or_output() -> None:
    rows = [
        row("Gi0/1", input_rate="900000000", output_rate="1"),
        row("Gi0/2", input_rate="1", output_rate="800000000"),
    ]

    by_out = iu.summarize_utilization(rows, sort_by="output")
    by_in = iu.summarize_utilization(rows, sort_by="input")

    assert by_out.findings[0]["interface"] == "Gi0/2"
    assert by_in.findings[0]["interface"] == "Gi0/1"


def test_interfaces_without_a_percentage_come_last() -> None:
    rows = [row("Gi0/1", input_rate="", output_rate=""), row("Gi0/2", input_rate="1000000")]

    summary = iu.summarize_utilization(rows)

    assert [f["interface"] for f in summary.findings] == ["Gi0/2", "Gi0/1"]


def test_a_named_interface_matches_by_abbreviation_and_includes_subinterfaces() -> None:
    rows = [row("GigabitEthernet0/1"), row("GigabitEthernet0/1.100"), row("GigabitEthernet0/10")]

    summary = iu.summarize_utilization(rows, interface="Gi0/1")

    assert {f["interface"] for f in summary.findings} == {
        "GigabitEthernet0/1",
        "GigabitEthernet0/1.100",
    }


def test_an_abbreviation_of_two_interface_types_is_a_clash() -> None:
    rows = [row("Serial0/1"), row("Service-Engine0/1")]

    summary = iu.summarize_utilization(rows, interface="Se0/1")

    assert summary.findings == ()
    assert set(summary.ambiguous) == {"Serial0/1", "Service-Engine0/1"}


def test_rows_of_other_commands_and_failed_commands_are_not_interfaces() -> None:
    rows = [row("Gi0/1"), neighbor("Gig 0/1"), {"_command": "show x", "_error": "no template"}]

    summary = iu.summarize_utilization(rows)

    assert summary.interfaces_in_output == 1
    assert summary.unparsed == 1


# -- neighbours: uplinks and downlinks ---------------------------------------------------------


def test_a_cdp_neighbor_marks_its_port_whatever_the_spelling() -> None:
    rows = [row("GigabitEthernet1/0/1"), row("GigabitEthernet1/0/2"), neighbor("Gig 1/0/1")]

    summary = iu.summarize_utilization(rows)

    by_name = {f["interface"]: f for f in summary.findings}
    assert by_name["GigabitEthernet1/0/1"]["neighbors"] == [
        {
            "name": "sw2.lab",
            "platform": "WS-C3850",
            "capabilities": "R S I",
            "port": "Gig 1/0/48",
        }
    ]
    assert "neighbors" not in by_name["GigabitEthernet1/0/2"]
    assert summary.neighbor_data == "available"


def test_only_neighbor_facing_keeps_the_ports_with_a_neighbor() -> None:
    rows = [
        row("Gi1/0/1", input_rate="1"),
        row("Gi1/0/2", input_rate="900000000"),
        neighbor("Gi1/0/1"),
    ]

    summary = iu.summarize_utilization(rows, only="neighbor_facing")

    assert [f["interface"] for f in summary.findings] == ["Gi1/0/1"]
    assert summary.interfaces_in_output == 2
    assert summary.interfaces_checked == 1


def test_two_neighbors_on_one_port_are_both_listed() -> None:
    rows = [row("Gi1/0/1"), neighbor("Gi1/0/1", "a"), neighbor("Gi1/0/1", "b")]

    (finding,) = iu.summarize_utilization(rows).findings

    assert [n["name"] for n in finding["neighbors"]] == ["a", "b"]


def test_without_neighbor_rows_the_neighbor_data_is_missing_not_empty() -> None:
    summary = iu.summarize_utilization([row("Gi0/1")], only="neighbor_facing")

    assert summary.neighbor_data == "not_in_handle"
    assert summary.findings == ()


def test_a_failed_neighbor_command_is_reported_as_such() -> None:
    rows = [row("Gi0/1"), {"_command": CDP, "_error": "no template"}]

    summary = iu.summarize_utilization(rows)

    assert summary.neighbor_data == "command_failed"


def test_lldp_rows_count_like_cdp_rows() -> None:
    rows = [row("Gi0/1"), neighbor("Gi0/1", _command="show lldp neighbors")]

    assert iu.summarize_utilization(rows).neighbor_data == "available"


def test_the_input_rows_are_not_changed() -> None:
    rows = [row("Gi0/1", input_rate="5"), neighbor("Gi0/1")]
    before = json.dumps(rows, sort_keys=True)

    iu.summarize_utilization(rows, only="neighbor_facing")

    assert json.dumps(rows, sort_keys=True) == before


# -- the tool ----------------------------------------------------------------------------------


@pytest.fixture
def store() -> ResultStore:
    return ResultStore(InMemoryResultBackend())


def _put(store: ResultStore, rows: list[dict[str, Any]], **overrides: Any) -> str:
    base: dict[str, Any] = {
        "kind": "parsed_output",
        "data_class": DataClass.CONTENT,
        "rows": rows,
        "meta": {"parser": "textfsm"},
    }
    base.update(overrides)
    return asyncio.run(store.put(USER, StoredResult(**base)))


def _ctx(store: ResultStore, *, content: bool = True) -> ToolContext:
    return ToolContext(
        user_id=USER,
        redactor=Redactor(),
        extras={RESULT_STORE_KEY: store},
        sharing=SharingPolicy(content=content),
    )


def _call(ctx: ToolContext, **args: Any):
    (tool,) = iut.build_interface_utilization_tools()
    return asyncio.run(tool.handler(ctx, tool.input_model(**args)))


def test_there_is_one_read_tool_that_cannot_reach_a_device() -> None:
    (tool,) = iut.build_interface_utilization_tools()

    assert tool.name == "summarize_interface_utilization"
    assert set(tool.input_model.model_fields) == {"handle", "interface", "only", "sort_by"}


def test_the_answer_has_the_busiest_interfaces_and_the_caveats(store) -> None:
    handle = _put(store, [row("Gi0/1", input_rate="100000000"), row("Gi0/2", output_rate="9")])

    out = _call(_ctx(store), handle=handle)

    assert not out.is_error
    payload = json.loads(out.content)
    assert [r["interface"] for r in payload["rows"]] == ["Gi0/1", "Gi0/2"]
    assert payload["summary"]["busiest"] == {
        "interface": "Gi0/1",
        "percent": 10.0,
        "by": "peak_percent",
    }
    assert payload["summary"]["complete"] is True
    assert "average" in payload["note"]
    assert "BW" in payload["note"]


def test_the_model_sees_at_most_one_preview_however_many_interfaces(store) -> None:
    rows = [row(f"Ethernet1/{n}", input_rate=str((n + 1) * 1_000_000)) for n in range(300)]

    payload = json.loads(_call(_ctx(store), handle=_put(store, rows)).content)

    assert len(payload["rows"]) == 20
    assert payload["total_rows"] == 300
    assert payload["rows"][0]["interface"] == "Ethernet1/299"
    stored = asyncio.run(store.get(USER, payload["handle"]))
    assert stored is not None and stored.data_class is DataClass.CONTENT
    assert len(out_text := json.dumps(payload)) < 20_000, out_text[:50]


def test_neighbor_facing_without_neighbor_data_is_an_error_not_no_uplinks(store) -> None:
    out = _call(_ctx(store), handle=_put(store, [row("Gi0/1")]), only="neighbor_facing")

    assert out.is_error
    assert "show cdp neighbors" in out.content


def test_neighbor_facing_with_a_failed_neighbor_command_is_an_error(store) -> None:
    handle = _put(store, [row("Gi0/1"), {"_command": CDP, "_error": "no template"}])

    out = _call(_ctx(store), handle=handle, only="neighbor_facing")

    assert out.is_error


def test_neighbor_facing_answers_with_the_neighbors(store) -> None:
    handle = _put(store, [row("Gi1/0/1", input_rate="5"), row("Gi1/0/2"), neighbor("Gig 1/0/1")])

    payload = json.loads(_call(_ctx(store), handle=handle, only="neighbor_facing").content)

    assert [r["interface"] for r in payload["rows"]] == ["Gi1/0/1"]
    assert payload["rows"][0]["neighbors"][0]["name"] == "sw2.lab"
    assert payload["summary"]["neighbor_facing_interfaces"] == 1
    assert "uplink or downlink" in payload["note"]


def test_a_cut_output_is_reported_as_possibly_incomplete(store) -> None:
    payload = json.loads(
        _call(_ctx(store), handle=_put(store, [row("Gi0/1")], partial=True)).content
    )

    assert payload["summary"]["complete"] is False
    assert "may be missing" in payload["note"]


def test_an_unknown_interface_name_is_an_error(store) -> None:
    out = _call(_ctx(store), handle=_put(store, [row("Gi0/1")]), interface="Gi9/9")

    assert out.is_error


def test_an_ambiguous_interface_name_is_an_error_with_the_names(store) -> None:
    handle = _put(store, [row("Serial0/1"), row("Service-Engine0/1")])

    out = _call(_ctx(store), handle=handle, interface="Se0/1")

    assert out.is_error
    assert "Serial0/1" in out.content


def test_rows_without_rates_are_an_error_naming_the_columns(store) -> None:
    handle = _put(store, [{"_command": "show interfaces", "interface": "e1", "mtu": "1500"}])

    out = _call(_ctx(store), handle=handle)

    assert out.is_error
    assert "mtu" in out.content


def test_rows_that_are_not_show_interfaces_are_an_error_with_a_pointer(store) -> None:
    out = _call(_ctx(store), handle=_put(store, [{"_command": "show version", "hostname": "r1"}]))

    assert out.is_error
    assert "show interfaces" in out.content


def test_a_raw_output_handle_is_pointed_to_the_parser(store) -> None:
    handle = asyncio.run(
        store.put(
            USER,
            StoredResult(kind="device_command", data_class=DataClass.CONTENT, text="Eth0/0 is up"),
        )
    )

    out = _call(_ctx(store), handle=handle)

    assert out.is_error
    assert "parse_command_output" in out.content


def test_content_sharing_off_gives_the_not_shared_marker(store) -> None:
    out = _call(_ctx(store, content=False), handle=_put(store, [row("Ethernet0/0")]))

    assert "not_shared" in out.content
    assert "Ethernet0/0" not in out.content


def test_another_users_or_an_unknown_handle_is_not_found(store) -> None:
    other = asyncio.run(
        store.put(
            USER + 1,
            StoredResult(kind="parsed_output", data_class=DataClass.CONTENT, rows=[row("e1")]),
        )
    )

    assert _call(_ctx(store), handle=other).is_error
    assert _call(_ctx(store), handle="res_000000000000").is_error


def test_device_and_neighbor_text_is_redacted(store) -> None:
    secret = "enable secret 5 $1$abcd$xyzxyzxyz"
    handle = _put(
        store,
        [row("Gi0/1", description=secret, input_rate="1"), neighbor("Gi0/1", name=secret)],
    )

    out = _call(_ctx(store), handle=handle)

    assert "$1$abcd$xyzxyzxyz" not in out.content


# -- review findings (doc/analysis/REVIEW.md, 2026-11-17) ---------------------------------------


def test_busiest_follows_the_sort_key_and_names_it() -> None:
    rows = [
        row("Gi0/1", input_rate="900000000", output_rate="500000000"),
        row("Gi0/2", input_rate="100000000", output_rate="400000000"),
    ]

    by_out = iu.summarize_utilization(rows, sort_by="output").busiest
    by_in = iu.summarize_utilization(rows, sort_by="input").busiest
    by_peak = iu.summarize_utilization(rows).busiest

    assert by_out == {"interface": "Gi0/1", "percent": 50.0, "by": "utilization_out_percent"}
    assert by_in == {"interface": "Gi0/1", "percent": 90.0, "by": "utilization_in_percent"}
    assert by_peak == {"interface": "Gi0/1", "percent": 90.0, "by": "peak_percent"}


def test_a_cut_output_names_no_busiest_interface(store) -> None:
    handle = _put(store, [row("Gi0/1", input_rate="900000000")], partial=True)

    summary = json.loads(_call(_ctx(store), handle=handle).content)["summary"]

    assert summary["busiest"] is None
    assert "incomplete" in summary["busiest_withheld"]


def test_a_command_that_did_not_parse_also_withholds_busiest(store) -> None:
    rows = [row("Gi0/1", input_rate="9"), {"_command": "show version", "_error": "no template"}]

    summary = json.loads(_call(_ctx(store), handle=_put(store, rows)).content)["summary"]

    assert summary["busiest"] is None


def test_a_complete_output_names_the_busiest_interface(store) -> None:
    summary = json.loads(
        _call(_ctx(store), handle=_put(store, [row("Gi0/1", input_rate="500000000")])).content
    )["summary"]

    assert summary["busiest"]["interface"] == "Gi0/1"
    assert summary["busiest_withheld"] is None


def test_neighbor_facing_on_a_cut_output_is_an_error_not_a_subset(store) -> None:
    handle = _put(store, [row("Gi1/0/1"), neighbor("Gi1/0/1")], partial=True)

    out = _call(_ctx(store), handle=handle, only="neighbor_facing")

    assert out.is_error
    assert "cut" in out.content
    assert "uplinks" in out.content


def test_a_cut_output_without_neighbor_filter_is_still_answered(store) -> None:
    handle = _put(store, [row("Gi1/0/1"), neighbor("Gi1/0/1")], partial=True)

    assert not _call(_ctx(store), handle=handle).is_error
