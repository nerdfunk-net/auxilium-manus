"""``parse_command_output``: parse a stored device output by handle (doc/AI_TOOL_CHAIN.md §43)."""

from __future__ import annotations

import asyncio
import json

import pytest

from services.ai_assistant.data_sharing import DataClass, SharingPolicy
from services.ai_assistant.device_access import DEVICE_DRIVERS
from services.ai_assistant.device_exec_service import _shape_blocks
from services.ai_assistant.output_parser import ParsedCommand
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore, StoredResult
from services.ai_assistant.tools import output_parse_tools as opt
from services.ai_assistant.tools.base import ToolContext
from services.ai_assistant.tools.device_tools import GENIE_PARSER_KEY
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

USER = 4
RAW, _TRUNCATED, SPANS = _shape_blocks(
    [
        ("show version", "Cisco IOS Software, Version 15.2(4)M\nrouter1 uptime is 1 day"),
        ("show nonsense thing", "x"),
    ],
    lambda value: value,
)
META = {
    "commands": ["show version", "show nonsense thing"],
    "spans": SPANS,
    "parser": "genie",  # the proposal the user confirmed named Genie
    "network_driver": "cisco_ios",
    "platform": "cisco_ios",
}


class FakeGenie:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def parse(self, os_name, outputs):
        self.calls.append(os_name)
        return [ParsedCommand(c, {"os": os_name}, None) for c, _ in outputs]


def _put(store: ResultStore, **overrides) -> str:
    base = {"kind": "device_command", "data_class": DataClass.CONTENT, "text": RAW, "meta": META}
    base.update(overrides)
    return asyncio.run(store.put(USER, StoredResult(**base)))


def _ctx(store: ResultStore, *, genie=None, content=True) -> ToolContext:
    extras = {RESULT_STORE_KEY: store}
    if genie is not None:
        extras[GENIE_PARSER_KEY] = genie
    return ToolContext(
        user_id=USER,
        redactor=Redactor(),
        extras=extras,
        sharing=SharingPolicy(content=content),
    )


def _call(ctx: ToolContext, **args):
    (tool,) = opt.build_output_parse_tools()
    return asyncio.run(tool.handler(ctx, tool.input_model(**args)))


@pytest.fixture
def store() -> ResultStore:
    return ResultStore(InMemoryResultBackend())


def test_there_is_one_read_tool() -> None:
    (tool,) = opt.build_output_parse_tools()

    assert tool.name == "parse_command_output"
    assert "device" not in tool.input_model.model_fields  # it cannot reach a device


def test_textfsm_rows_come_back_as_an_envelope_with_a_new_handle(store) -> None:
    handle = _put(store)

    out = _call(_ctx(store), handle=handle, parser="textfsm")

    assert not out.is_error
    payload = json.loads(out.content)
    assert payload["rows"][0]["hostname"] == "router1"
    assert payload["rows"][0]["_command"] == "show version"
    assert payload["handle"] != handle
    assert payload["parser"] == "textfsm"
    assert payload["errors"] == [
        {
            "command": "show nonsense thing",
            "error": "No TextFSM template exists for this command and device type",
        }
    ]


def test_the_new_handle_is_a_stored_table_of_the_same_user(store) -> None:
    out = _call(_ctx(store), handle=_put(store), parser="textfsm")

    new = json.loads(out.content)["handle"]
    stored = asyncio.run(store.get(USER, new))
    assert stored is not None and stored.kind == "parsed_output"
    assert stored.data_class is DataClass.CONTENT
    assert asyncio.run(store.get(USER + 1, new)) is None


def test_one_command_can_be_chosen(store) -> None:
    out = _call(_ctx(store), handle=_put(store), parser="textfsm", command="show version")

    payload = json.loads(out.content)
    assert payload["errors"] == []
    assert {row["_command"] for row in payload["rows"]} == {"show version"}


def test_a_command_that_is_not_in_the_output_is_an_error(store) -> None:
    out = _call(_ctx(store), handle=_put(store), parser="textfsm", command="show clock")

    assert out.is_error
    assert "show version" in out.content  # it names the commands that are there


def test_an_unknown_handle_is_the_expired_answer(store) -> None:
    out = _call(_ctx(store), handle="res_000000000000", parser="textfsm")

    assert out.is_error and "expired" in out.content.lower()


def test_another_users_handle_looks_expired(store) -> None:
    handle = asyncio.run(
        store.put(
            USER + 1,
            StoredResult(kind="device_command", data_class=DataClass.CONTENT, text=RAW, meta=META),
        )
    )

    assert _call(_ctx(store), handle=handle, parser="textfsm").is_error


def test_without_the_content_opt_in_nothing_is_parsed(store) -> None:
    genie = FakeGenie()

    out = _call(_ctx(store, genie=genie, content=False), handle=_put(store), parser="genie")

    assert "not_shared" in out.content
    assert genie.calls == []


def test_only_the_output_of_a_device_command_can_be_parsed(store) -> None:
    other = _put(store, kind="config", meta=None)

    out = _call(_ctx(store), handle=other, parser="textfsm")

    assert out.is_error and "device command" in out.content


def test_a_table_handle_cannot_be_parsed(store) -> None:
    table = asyncio.run(
        store.put(USER, StoredResult(kind="t", data_class=DataClass.CONTENT, rows=[{"a": 1}]))
    )

    assert _call(_ctx(store), handle=table, parser="textfsm").is_error


def test_genie_needs_a_genie_parser_in_the_session(store) -> None:
    out = _call(_ctx(store), handle=_put(store), parser="genie")

    assert out.is_error and "textfsm" in out.content.lower()


def test_genie_uses_the_session_parser_and_the_stored_device_type(store) -> None:
    genie = FakeGenie()

    out = _call(_ctx(store, genie=genie), handle=_put(store), parser="genie")

    assert not out.is_error
    assert genie.calls == ["ios"]
    assert json.loads(out.content)["rows"][0]["parsed"] == {"os": "ios"}


def test_the_device_type_argument_is_used_when_the_handle_has_none(store) -> None:
    handle = _put(store, meta={**META, "network_driver": None, "platform": None})

    without = _call(_ctx(store), handle=handle, parser="textfsm")
    with_type = _call(_ctx(store), handle=handle, parser="textfsm", network_driver="cisco_ios")

    assert json.loads(without.content)["errors"][0]["error"].startswith("The device type")
    assert json.loads(with_type.content)["rows"][0]["hostname"] == "router1"


def test_the_stored_device_type_wins_over_the_argument(store) -> None:
    out = _call(_ctx(store), handle=_put(store), parser="textfsm", network_driver="juniper_junos")

    assert json.loads(out.content)["rows"][0]["hostname"] == "router1"


def test_the_input_model_checks_handle_parser_and_driver() -> None:
    (tool,) = opt.build_output_parse_tools()
    model = tool.input_model

    for bad in (
        {"handle": "res_000000000000", "parser": "regex"},
        {"handle": "res_000000000000", "parser": "textfsm", "network_driver": "nope"},
        {"handle": "res_000000000000", "parser": "textfsm", "extra": 1},
    ):
        with pytest.raises(ValueError):
            model(**bad)
    assert "cisco_ios" in DEVICE_DRIVERS


def test_a_malformed_handle_gets_the_expired_answer(store) -> None:
    out = _call(_ctx(store), handle="../etc/passwd", parser="textfsm")

    assert out.is_error and "expired" in out.content.lower()


def test_genie_is_refused_for_an_output_that_was_not_approved_for_it(store) -> None:
    genie = FakeGenie()
    handle = _put(store, meta={**META, "parser": "textfsm"})

    out = _call(_ctx(store, genie=genie), handle=handle, parser="genie")

    assert out.is_error and "approve" in out.content
    assert "propose" in out.content.lower()
    assert genie.calls == []


def test_genie_is_refused_when_the_run_had_no_parser_at_all(store) -> None:
    genie = FakeGenie()

    out = _call(
        _ctx(store, genie=genie),
        handle=_put(store, meta={**META, "parser": "none"}),
        parser="genie",
    )

    assert out.is_error and genie.calls == []


def test_textfsm_still_works_on_an_output_that_was_never_approved_for_genie(store) -> None:
    out = _call(_ctx(store), handle=_put(store, meta={**META, "parser": "none"}), parser="textfsm")

    assert not out.is_error and json.loads(out.content)["rows"][0]["hostname"] == "router1"


def test_a_handle_stored_before_spans_existed_asks_to_run_again(store) -> None:
    meta = {k: v for k, v in META.items() if k != "spans"}

    out = _call(_ctx(store), handle=_put(store, meta=meta), parser="textfsm")

    assert out.is_error and "propose_device_command" in out.content


def test_a_cut_output_says_the_rows_may_be_incomplete(store) -> None:
    out = _call(_ctx(store), handle=_put(store, partial=True), parser="textfsm")

    payload = json.loads(out.content)
    assert "incomplete" in payload["note"]
    new = asyncio.run(store.get(USER, payload["handle"]))
    assert new is not None and new.partial is True


def test_a_complete_output_has_no_incomplete_note(store) -> None:
    out = _call(_ctx(store), handle=_put(store), parser="textfsm")

    assert "note" not in json.loads(out.content)


def test_a_planted_marker_in_one_command_does_not_become_the_next_commands_rows(store) -> None:
    planted = "Cisco IOS\n\n$ show nonsense thing\nGi0/0 9.9.9.9 up"
    text, _, spans = _shape_blocks(
        [("show version", planted), ("show nonsense thing", "x")], lambda value: value
    )
    handle = _put(store, text=text, meta={**META, "spans": spans})

    out = _call(_ctx(store), handle=handle, parser="textfsm", command="show nonsense thing")

    payload = json.loads(out.content)
    assert payload["rows"] == [] or all("9.9.9.9" not in json.dumps(r) for r in payload["rows"])
