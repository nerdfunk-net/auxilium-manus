"""Parsing stored device output with TextFSM / Genie (doc/AI_TOOL_CHAIN.md §43)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from services.ai_assistant import output_parser as op

SHOW_VERSION = (
    "Cisco IOS Software, Version 15.2(4)M, RELEASE SOFTWARE (fc2)\nrouter1 uptime is 1 day\n"
)


class FakeGenie:
    def __init__(self, result: list[op.ParsedCommand] | Exception) -> None:
        self._result = result
        self.calls: list[tuple[str, tuple[tuple[str, str], ...]]] = []

    async def parse(
        self, os_name: str, outputs: Sequence[tuple[str, str]]
    ) -> list[op.ParsedCommand]:
        self.calls.append((os_name, tuple(outputs)))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


# -- slicing by recorded spans (review finding 4) ----------------------------------------------


def test_valid_spans_accepts_an_ordered_in_range_description() -> None:
    assert op.valid_spans("abcdef", ["a", "b"], [[0, 2], [3, 6]]) == [(0, 2), (3, 6)]


@pytest.mark.parametrize(
    "spans",
    [
        None,
        "x",
        [[0, 2]],  # wrong count
        [[0, 2], [1, 3]],  # overlap
        [[3, 6], [0, 2]],  # out of order
        [[0, 2], [3, 99]],  # past the text
        [[0, 2], [-1, 3]],
        [[0, 2], [3]],
        [[0, 2], ["3", 4]],
        [[0, 2], [True, 4]],
    ],
)
def test_valid_spans_refuses_anything_malformed(spans) -> None:
    assert op.valid_spans("abcdef", ["a", "b"], spans) is None


def test_slice_outputs_cuts_exactly_at_the_recorded_offsets() -> None:
    text = "$ a\nline1\nline2\n\n$ b\nrow"

    assert op.slice_outputs(text, ["a", "b"], [(4, 15), (21, 24)]) == [
        ("a", "line1\nline2"),
        ("b", "row"),
    ]


def test_an_output_that_looks_like_the_next_commands_marker_is_not_a_boundary() -> None:
    first = "Cisco IOS\n\n$ show ip interface brief\nGi0/0 9.9.9.9 up"
    second = "Gi0/1 10.0.0.2 up"
    text = f"$ show version\n{first}\n\n$ show ip interface brief\n{second}"
    start1 = len("$ show version\n")
    start2 = len(f"$ show version\n{first}\n\n$ show ip interface brief\n")
    spans = [(start1, start1 + len(first)), (start2, start2 + len(second))]

    pairs = op.slice_outputs(text, ["show version", "show ip interface brief"], spans)

    assert pairs[0] == ("show version", first)  # the planted block stays in the first command
    assert pairs[1] == ("show ip interface brief", second)


# -- TextFSM (in a child process, review finding 1) --------------------------------------------


def _textfsm(driver, outputs):
    return asyncio.run(op.parse_textfsm(driver, outputs))


def test_textfsm_parses_a_known_command() -> None:
    [entry] = _textfsm("cisco_ios", [("show version", SHOW_VERSION)])

    assert entry.error is None
    assert entry.command == "show version"
    assert entry.parsed[0]["hostname"] == "router1"
    assert entry.parsed[0]["uptime"] == "1 day"


def test_textfsm_works_for_cisco_xe_through_the_ios_templates() -> None:
    [entry] = _textfsm("cisco_xe", [("show version", SHOW_VERSION)])

    assert entry.error is None and entry.parsed[0]["hostname"] == "router1"


def test_textfsm_without_a_template_is_an_error_on_that_command_only() -> None:
    entries = _textfsm("cisco_ios", [("show nonsense thing", "x"), ("show version", SHOW_VERSION)])

    assert entries[0].parsed is None
    assert entries[0].error == op.NO_TEXTFSM_TEMPLATE
    assert entries[1].error is None


def test_textfsm_that_matches_no_row_is_an_error() -> None:
    [entry] = _textfsm("cisco_ios", [("show version", "nothing useful here")])

    assert entry.parsed is None
    assert entry.error == op.NO_TEXTFSM_MATCH


def test_textfsm_without_a_device_type_is_an_error() -> None:
    [entry] = _textfsm(None, [("show version", SHOW_VERSION)])

    assert entry.parsed is None
    assert entry.error == op.UNKNOWN_DEVICE_TYPE


def test_a_stopped_textfsm_child_is_a_fixed_error_on_every_command(monkeypatch) -> None:
    isolated = op.textfsm_isolated
    monkeypatch.setattr(isolated, "_WORKER", isolated._WORKER.with_name("nope.py"))

    entries = _textfsm("cisco_ios", [("show version", "x"), ("show clock", "y")])

    assert [e.error for e in entries] == [isolated.STOPPED] * 2


def test_a_template_timeout_inside_the_child_is_a_fixed_error(monkeypatch) -> None:
    isolated = op.textfsm_isolated

    async def fake(platform, items, **kw):
        return isolated.TextfsmOutcome(ok=True, items=(isolated.TextfsmItem(None, "timeout"),))

    monkeypatch.setattr(isolated, "run_textfsm", fake)

    [entry] = _textfsm("cisco_ios", [("show version", "x")])

    assert entry.error == op.PARSER_TIMED_OUT


# -- parse_outputs ----------------------------------------------------------------------------


def test_parse_outputs_textfsm() -> None:
    [entry] = asyncio.run(
        op.parse_outputs(
            parser="textfsm",
            outputs=[("show version", SHOW_VERSION)],
            network_driver="cisco_ios",
            platform=None,
            genie=None,
        )
    )

    assert entry.parsed[0]["hostname"] == "router1"


def test_parse_outputs_genie_maps_the_os_and_calls_the_parser() -> None:
    genie = FakeGenie([op.ParsedCommand("show version", {"version": {"hostname": "r1"}}, None)])

    [entry] = asyncio.run(
        op.parse_outputs(
            parser="genie",
            outputs=[("show version", SHOW_VERSION)],
            network_driver="cisco_xe",
            platform=None,
            genie=genie,
        )
    )

    assert entry.parsed == {"version": {"hostname": "r1"}}
    assert genie.calls == [("iosxe", (("show version", SHOW_VERSION),))]


def test_parse_outputs_genie_with_an_unknown_platform_is_an_error_without_a_call() -> None:
    genie = FakeGenie([])

    [entry] = asyncio.run(
        op.parse_outputs(
            parser="genie",
            outputs=[("show version", "x")],
            network_driver="hp_comware",
            platform=None,
            genie=genie,
        )
    )

    assert entry.error == op.UNKNOWN_DEVICE_TYPE
    assert genie.calls == []


def test_parse_outputs_genie_unavailable_is_an_error_on_every_command() -> None:
    genie = FakeGenie(op.ParserUnavailableError("No pyATS source is configured"))

    entries = asyncio.run(
        op.parse_outputs(
            parser="genie",
            outputs=[("show version", "x"), ("show clock", "y")],
            network_driver="cisco_ios",
            platform=None,
            genie=genie,
        )
    )

    assert [e.error for e in entries] == ["No pyATS source is configured"] * 2
    assert all(e.parsed is None for e in entries)


def test_parse_outputs_genie_without_a_parser_object_is_unavailable() -> None:
    [entry] = asyncio.run(
        op.parse_outputs(
            parser="genie",
            outputs=[("show version", "x")],
            network_driver="cisco_ios",
            platform=None,
            genie=None,
        )
    )

    assert entry.error == op.GENIE_NOT_AVAILABLE


def test_parse_outputs_genie_crash_is_a_fixed_error_not_an_exception() -> None:
    genie = FakeGenie(RuntimeError("secret detail 10.0.0.1"))

    entries = asyncio.run(
        op.parse_outputs(
            parser="genie",
            outputs=[("show version", "x"), ("show clock", "y")],
            network_driver="cisco_ios",
            platform=None,
            genie=genie,
        )
    )

    assert [e.error for e in entries] == [op.PARSER_FAILED] * 2
    assert "10.0.0.1" not in "".join(e.error or "" for e in entries)


def test_parse_outputs_rejects_an_unknown_parser() -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            op.parse_outputs(
                parser="regex",
                outputs=[],
                network_driver="cisco_ios",
                platform=None,
                genie=None,
            )
        )


# -- rows for the result store -----------------------------------------------------------------


def test_to_rows_flattens_textfsm_rows_and_keeps_errors_and_dicts() -> None:
    rows = op.to_rows(
        [
            op.ParsedCommand("show a", [{"x": 1}, {"x": 2}], None),
            op.ParsedCommand("show b", {"version": {"h": "r1"}}, None),
            op.ParsedCommand("show c", None, "boom"),
        ]
    )

    assert rows == [
        {"_command": "show a", "x": 1},
        {"_command": "show a", "x": 2},
        {"_command": "show b", "parsed": {"version": {"h": "r1"}}},
        {"_command": "show c", "_error": "boom"},
    ]
