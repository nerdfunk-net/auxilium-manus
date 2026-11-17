"""``summarize_interface_errors``: error and drop counters of parsed ``show interfaces`` rows.

doc/AI_TOOL_CHAIN.md §54.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from services.ai_assistant import interface_errors as ie
from services.ai_assistant.data_sharing import DataClass, SharingPolicy
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore, StoredResult
from services.ai_assistant.tools import interface_error_tools as iet
from services.ai_assistant.tools.base import ToolContext
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

USER = 4

# One interface of a real TextFSM 'show interfaces' result (every value is a string).
CLEAN = {
    "_command": "show interfaces",
    "interface": "Ethernet0/0",
    "link_status": "up",
    "protocol_status": "up",
    "description": "Ethernet 0/0",
    "input_packets": "1682077",
    "output_packets": "118050",
    "runts": "0",
    "giants": "0",
    "input_errors": "0",
    "crc": "0",
    "frame": "0",
    "overrun": "0",
    "abort": "",
    "output_errors": "0",
    "queue_drops": "0",
    "queue_flushes": "0",
    "queue_output_drops": "0",
}


def row(name: str, **values: str) -> dict[str, Any]:
    return {**CLEAN, "interface": name, "description": "", **values}


# -- counter values ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", 0), ("17", 17), (" 5 ", 5), (9, 9), ("", None), (None, None), ("n/a", None)]
    + [("-3", None), (-3, None), (True, None), ("1.5", None), ("１２", None)],
)
def test_a_counter_is_an_integer_and_empty_is_not_zero(raw: object, expected: int | None) -> None:
    assert ie.counter_value(raw) == expected


def test_the_allow_list_is_the_two_groups_and_leaves_queue_flushes_out() -> None:
    assert ie.ERROR_COUNTERS[:8] == (
        "input_errors",
        "output_errors",
        "crc",
        "frame",
        "overrun",
        "abort",
        "runts",
        "giants",
    )
    # NX-OS columns: not part of input_errors, so the IOS names alone would call it clean.
    assert {"stomped_crc", "short_frame"} <= set(ie.ERROR_COUNTERS)
    assert {"input_discards", "output_discards"} <= set(ie.DROP_COUNTERS)
    assert ie.DROP_COUNTERS[:2] == ("queue_drops", "queue_output_drops")
    assert "queue_flushes" not in ie.ALL_COUNTERS


# -- interface names ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "wanted", "expected"),
    [
        ("GigabitEthernet0/1", "GigabitEthernet0/1", True),
        ("GigabitEthernet0/1", "gigabitethernet0/1", True),
        ("GigabitEthernet0/1", "Gi0/1", True),
        ("GigabitEthernet0/10", "Gi0/1", False),
        ("TenGigabitEthernet1/0/1", "Te1/0/1", True),
        ("Port-channel1", "Po1", True),
        ("Ethernet0/0", "Eth0/0", True),
        ("GigabitEthernet0/1", "G0/1", False),  # one letter is not an abbreviation
        ("GigabitEthernet0/1", "Gi0/2", False),
        ("GigabitEthernet0/1", "Gi", False),
        ("GigabitEthernet0/1", "", False),
        ("Vlan10", "Vl10", True),
        ("GigabitEthernet0/0/0.100", "Gi0/0/0.100", True),
    ],
)
def test_an_interface_is_named_in_full_or_by_an_abbreviation(
    name: str, wanted: str, expected: bool
) -> None:
    assert ie.interface_matches(name, wanted) is expected


# -- the summary -------------------------------------------------------------------------------


def test_a_device_without_counters_is_clean() -> None:
    summary = ie.summarize_interface_errors([row("Ethernet0/0"), row("Ethernet0/1")])

    assert summary.findings == ()
    assert (summary.interfaces_in_output, summary.interfaces_checked) == (2, 2)
    assert summary.interfaces_with_problems == 0
    assert summary.counter_totals == {}


def test_only_interfaces_with_a_non_zero_counter_are_reported_worst_first() -> None:
    rows = [
        row("Ethernet0/0"),
        row("Ethernet0/1", crc="3", input_errors="3"),
        row("Ethernet0/2", queue_output_drops="900"),
        row("Ethernet0/3", output_errors="1"),
    ]

    summary = ie.summarize_interface_errors(rows)

    assert [f["interface"] for f in summary.findings] == [
        "Ethernet0/2",
        "Ethernet0/1",
        "Ethernet0/3",
    ]
    assert summary.interfaces_with_problems == 3
    assert (summary.interfaces_with_errors, summary.interfaces_with_drops) == (2, 1)
    # Counters are reported one by one; input_errors already contains the crc errors.
    assert summary.findings[1]["errors"] == {"input_errors": 3, "crc": 3}
    assert summary.counter_totals == {
        "queue_output_drops": 900,
        "input_errors": 3,
        "crc": 3,
        "output_errors": 1,
    }


def test_each_finding_carries_the_packets_and_the_error_rate() -> None:
    (finding,) = ie.summarize_interface_errors(
        [row("Ethernet0/1", input_errors="168", queue_output_drops="59")]
    ).findings

    assert finding["input_packets"] == 1682077
    assert finding["output_packets"] == 118050
    assert finding["rates_percent"] == {
        "input_errors_percent": round(168 / 1682077 * 100, 6),
        "output_drops_percent": round(59 / 118050 * 100, 6),
    }
    assert finding["link_status"] == "up"


def test_an_empty_counter_is_not_reported_and_not_looked_at() -> None:
    summary = ie.summarize_interface_errors([row("Ethernet0/0", abort="", output_errors="")])

    assert "abort" not in summary.counters_looked_at
    assert "abort" in summary.counters_not_in_output
    assert "output_errors" in summary.counters_not_in_output
    assert "input_errors" in summary.counters_looked_at


def test_the_description_is_reported_only_when_there_is_one() -> None:
    rows = [
        row("Ethernet0/1", crc="1", description="uplink to core"),
        row("Ethernet0/2", crc="2"),
    ]

    by_name = {f["interface"]: f for f in ie.summarize_interface_errors(rows).findings}

    assert by_name["Ethernet0/1"]["description"] == "uplink to core"
    assert "description" not in by_name["Ethernet0/2"]


def test_a_named_interface_is_reported_even_when_it_is_clean() -> None:
    rows = [row("GigabitEthernet0/1"), row("GigabitEthernet0/2", crc="4")]

    summary = ie.summarize_interface_errors(rows, interface="Gi0/1")

    assert [f["interface"] for f in summary.findings] == ["GigabitEthernet0/1"]
    assert summary.findings[0]["errors"] == {}
    assert (summary.interfaces_in_output, summary.interfaces_checked) == (2, 1)
    assert summary.interfaces_with_problems == 0


def test_rows_that_are_not_interfaces_are_not_counted() -> None:
    rows = [row("Ethernet0/1", crc="1"), {"_command": "show foo", "_error": "No template"}]

    summary = ie.summarize_interface_errors(rows)

    assert summary.interfaces_in_output == 1
    assert summary.unparsed == 1


def test_the_input_rows_are_not_changed() -> None:
    rows = [row("Ethernet0/1", crc="1")]
    before = json.dumps(rows, sort_keys=True)

    ie.summarize_interface_errors(rows, interface="Eth0/1")

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
    (tool,) = iet.build_interface_error_tools()
    return asyncio.run(tool.handler(ctx, tool.input_model(**args)))


def test_there_is_one_read_tool_that_cannot_reach_a_device() -> None:
    (tool,) = iet.build_interface_error_tools()

    assert tool.name == "summarize_interface_errors"
    assert set(tool.input_model.model_fields) == {"handle", "interface"}
    assert "device" not in tool.input_model.model_fields


def test_the_answer_has_the_problem_interfaces_and_a_summary(store) -> None:
    handle = _put(store, [row("Ethernet0/0"), row("Ethernet0/1", crc="5", input_errors="5")])

    out = _call(_ctx(store), handle=handle)

    assert not out.is_error
    payload = json.loads(out.content)
    assert [r["interface"] for r in payload["rows"]] == ["Ethernet0/1"]
    summary = payload["summary"]
    assert (summary["interfaces_checked"], summary["interfaces_with_problems"]) == (2, 1)
    assert summary["clean"] is False
    assert summary["counter_totals"] == {"input_errors": 5, "crc": 5}
    assert "cumulative" in payload["note"]
    assert "handle" not in payload  # one preview is enough: no handle for a short result


def test_a_clean_device_says_so_and_returns_no_rows(store) -> None:
    out = _call(_ctx(store), handle=_put(store, [row("Ethernet0/0"), row("Ethernet0/1")]))

    payload = json.loads(out.content)
    assert payload["rows"] == []
    assert payload["summary"]["clean"] is True
    assert payload["summary"]["interfaces_checked"] == 2


def test_the_model_sees_at_most_one_preview_however_many_interfaces_are_bad(store) -> None:
    rows = [row(f"Ethernet1/{n}", crc=str(n + 1)) for n in range(300)]

    out = _call(_ctx(store), handle=_put(store, rows))

    payload = json.loads(out.content)
    assert len(payload["rows"]) == 20
    assert payload["total_rows"] == 300
    assert payload["truncated"] is True
    assert payload["summary"]["interfaces_with_problems"] == 300
    assert payload["rows"][0]["interface"] == "Ethernet1/299"  # the worst first
    stored = asyncio.run(store.get(USER, payload["handle"]))
    assert stored is not None and stored.rows is not None and len(stored.rows) == 300
    assert stored.data_class is DataClass.CONTENT
    assert len(out.content) < 20_000


def test_a_named_interface_is_answered_even_when_clean(store) -> None:
    handle = _put(store, [row("GigabitEthernet0/1"), row("GigabitEthernet0/2", crc="2")])

    payload = json.loads(_call(_ctx(store), handle=handle, interface="Gi0/1").content)

    assert [r["interface"] for r in payload["rows"]] == ["GigabitEthernet0/1"]
    assert payload["summary"]["clean"] is True
    assert payload["summary"]["rows_are"] == "the checked interfaces"


def test_an_unknown_interface_name_is_an_error(store) -> None:
    out = _call(_ctx(store), handle=_put(store, [row("Ethernet0/0")]), interface="Gi9/9")

    assert out.is_error
    assert "1 interfaces" in out.content


def test_a_cut_output_is_reported_as_possibly_incomplete(store) -> None:
    handle = _put(store, [row("Ethernet0/1", crc="1")], partial=True)

    payload = json.loads(_call(_ctx(store), handle=handle).content)

    assert "may be missing" in payload["note"]
    assert payload["total_rows_exact"] is False


def test_rows_that_are_not_show_interfaces_are_an_error_with_a_pointer(store) -> None:
    handle = _put(store, [{"_command": "show version", "hostname": "r1"}])

    out = _call(_ctx(store), handle=handle)

    assert out.is_error
    assert "show interfaces" in out.content


def test_a_template_without_our_counters_names_its_columns(store) -> None:
    handle = _put(store, [{"_command": "show interfaces", "interface": "e1", "speed": "10G"}])

    out = _call(_ctx(store), handle=handle)

    assert out.is_error
    assert "speed" in out.content
    assert "input_errors" in out.content


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


def test_device_text_in_a_description_is_redacted(store) -> None:
    secret_row = row("Ethernet0/1", crc="1", description="enable secret 5 $1$abcd$xyzxyzxyz")

    out = _call(_ctx(store), handle=_put(store, [secret_row]))

    assert "$1$abcd$xyzxyzxyz" not in out.content


# -- review findings (doc/analysis/REVIEW.md, 2026-11-17) ---------------------------------------


def nxos(name: str, **values: str) -> dict[str, Any]:
    """A row with the NX-OS template's columns: no IOS queue counters, discards instead."""
    base = {
        "_command": "show interfaces",
        "interface": name,
        "link_status": "up",
        "description": "",
        "input_packets": "1000000",
        "output_packets": "500000",
        "input_errors": "0",
        "output_errors": "0",
        "crc": "0",
        "runts": "0",
        "giants": "0",
        "overrun": "0",
        "input_discards": "0",
        "output_discards": "0",
        "stomped_crc": "0",
        "short_frame": "0",
    }
    return {**base, **values}


def test_nxos_discards_and_stomped_crc_are_not_reported_clean() -> None:
    rows = [nxos("Ethernet1/1", input_discards="4000", stomped_crc="15"), nxos("Ethernet1/2")]

    summary = ie.summarize_interface_errors(rows)

    assert summary.interfaces_with_problems == 1
    (finding,) = summary.findings
    assert finding["errors"] == {"stomped_crc": 15}
    assert finding["drops"] == {"input_discards": 4000}
    assert finding["rates_percent"]["input_drops_percent"] == 0.4


def test_a_cut_output_without_errors_is_not_clean(store) -> None:
    handle = _put(store, [row("Ethernet0/0"), row("Ethernet0/1")], partial=True)

    summary = json.loads(_call(_ctx(store), handle=handle).content)["summary"]

    assert summary["interfaces_with_problems"] == 0
    assert summary["complete"] is False
    assert summary["clean"] is False


def test_a_command_that_did_not_parse_means_not_clean(store) -> None:
    rows = [row("Ethernet0/0"), {"_command": "show foo", "_error": "No template"}]

    payload = json.loads(_call(_ctx(store), handle=_put(store, rows)).content)

    assert payload["summary"]["unparsed_commands"] == 1
    assert payload["summary"]["clean"] is False
    assert "did not parse" in payload["note"]


def test_a_complete_output_without_errors_is_clean(store) -> None:
    summary = json.loads(_call(_ctx(store), handle=_put(store, [row("Ethernet0/0")])).content)[
        "summary"
    ]

    assert (summary["complete"], summary["clean"]) == (True, True)


def test_a_platform_without_drop_counters_says_drops_were_not_checked(store) -> None:
    xr = {k: v for k, v in row("TenGigE0/0/0/1").items() if not k.startswith("queue")}

    payload = json.loads(_call(_ctx(store), handle=_put(store, [xr])).content)

    assert payload["summary"]["drops_checked"] is False
    assert payload["summary"]["errors_checked"] is True
    assert "NOT checked" in payload["note"]


def test_a_named_interface_includes_its_subinterfaces() -> None:
    rows = [
        row("GigabitEthernet0/1"),
        row("GigabitEthernet0/1.100", crc="50"),
        row("GigabitEthernet0/10", crc="9"),
    ]

    summary = ie.summarize_interface_errors(rows, interface="Gi0/1")

    assert sorted(f["interface"] for f in summary.findings) == [
        "GigabitEthernet0/1",
        "GigabitEthernet0/1.100",
    ]
    assert summary.interfaces_with_problems == 1  # the subinterface; the parent is not "clean"


def test_a_subinterface_name_matches_only_itself() -> None:
    assert ie.interface_matches("GigabitEthernet0/1.100", "Gi0/1.100")
    assert not ie.interface_matches("GigabitEthernet0/1.200", "Gi0/1.100")
    assert not ie.interface_matches("GigabitEthernet0/1", "Gi0/1.100")


@pytest.mark.parametrize(
    ("names", "wanted"),
    [
        (["Serial0/1", "Service-Engine0/1"], "Se0/1"),
        (["Port-channel1", "Port1"], "Po1"),
    ],
)
def test_an_abbreviation_of_two_interface_types_is_a_clash(names, wanted) -> None:
    assert ie.interface_type_clash(names, wanted) == tuple(names)


def test_a_full_name_or_a_single_type_is_not_a_clash() -> None:
    assert ie.interface_type_clash(["Port-channel1", "Port1"], "Port-channel1") == ()
    assert ie.interface_type_clash(["GigabitEthernet0/1", "GigabitEthernet0/1.5"], "Gi0/1") == ()
    assert ie.interface_type_clash(["Serial0/1"], "Se0/1") == ()


def test_a_clashing_abbreviation_is_refused_by_the_tool(store) -> None:
    handle = _put(store, [row("Serial0/1", crc="1"), row("Service-Engine0/1")])

    out = _call(_ctx(store), handle=handle, interface="Se0/1")

    assert out.is_error
    assert "Serial0/1" in out.content and "Service-Engine0/1" in out.content


def test_the_worst_first_order_does_not_add_overlapping_counters() -> None:
    rows = [
        row("Ethernet0/1", input_errors="100", crc="100"),  # one set of packets, counted twice
        row("Ethernet0/2", output_errors="150"),
    ]

    order = [f["interface"] for f in ie.summarize_interface_errors(rows).findings]

    assert order == ["Ethernet0/2", "Ethernet0/1"]
