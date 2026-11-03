"""Split, parse and store: what the executor and the parse tool share (§43)."""

from __future__ import annotations

import asyncio
import json

from services.ai_assistant import parse_service as ps
from services.ai_assistant.device_exec_service import _shape_blocks
from services.ai_assistant.data_sharing import DataClass
from services.ai_assistant.output_parser import ParsedCommand
from services.ai_assistant.results.store import (
    InMemoryResultBackend,
    ResultStore,
    ResultStoreUnavailableError,
)

SHOW_VERSION = "Cisco IOS Software, Version 15.2(4)M\nrouter1 uptime is 1 day\n"
COMMANDS = ["show version", "show nonsense thing"]


def _capture(*outputs):
    """The text and spans the executor stores for these ``(command, output)`` pairs."""
    text, _, spans = _shape_blocks(list(outputs), lambda value: value)
    return text, spans


TEXT, SPANS = _capture(("show version", SHOW_VERSION), ("show nonsense thing", "x"))


class FakeGenie:
    async def parse(self, os_name, outputs):
        return [ParsedCommand(c, {"os": os_name}, None) for c, _ in outputs]


def _parse(store=None, *, text=TEXT, spans=SPANS, parser="textfsm", genie=None, user_id=3, **kw):
    store = ResultStore(InMemoryResultBackend()) if store == "default" or store is None else store
    outcome = asyncio.run(
        ps.parse_stored_text(
            user_id=user_id,
            store=store,
            parser=parser,
            text=text,
            commands=COMMANDS,
            spans=spans,
            network_driver="cisco_ios",
            platform=None,
            genie=genie,
            source_handle="res_aaaaaaaaaaaa",
            **kw,
        )
    )
    return outcome, store


def test_parses_each_command_and_stores_the_rows_behind_a_handle() -> None:
    outcome, store = _parse()

    assert [e.error for e in outcome.entries] == [
        None,
        "No TextFSM template exists for this command and device type",
    ]
    assert outcome.handle is not None
    stored = asyncio.run(store.get(3, outcome.handle))
    assert stored is not None
    assert stored.kind == "parsed_output"
    assert stored.data_class is DataClass.CONTENT
    assert stored.rows is not None and stored.rows[0]["_command"] == "show version"
    assert stored.rows[0]["hostname"] == "router1"
    assert stored.meta == {"parser": "textfsm", "source_handle": "res_aaaaaaaaaaaa"}


def test_the_shown_text_is_the_json_of_the_rows() -> None:
    outcome, _ = _parse()

    shown = json.loads(outcome.text)
    assert shown[0]["command"] == "show version"
    assert shown[1]["parsed"] is None


def test_a_handle_is_not_made_when_nothing_parsed() -> None:
    text, spans = _capture(("show version", "nothing useful"), ("show nonsense thing", "x"))
    outcome, _ = _parse(text=text, spans=spans)

    assert outcome.handle is None
    assert all(e.error for e in outcome.entries)


def test_genie_uses_the_given_client() -> None:
    outcome, _ = _parse(parser="genie", genie=FakeGenie())

    assert outcome.entries[0].parsed == {"os": "ios"}


def test_an_unavailable_store_still_returns_the_parsed_data() -> None:
    class Down:
        async def put(self, user_id, result):
            raise ResultStoreUnavailableError

    outcome, _ = _parse(store=Down())

    assert outcome.handle is None
    assert outcome.entries[0].error is None


def test_a_result_too_large_to_store_has_no_handle_but_a_cut_text() -> None:
    class TooBig:
        async def put(self, user_id, result):
            raise ValueError("result is too large to store")

    outcome, _ = _parse(store=TooBig())

    assert outcome.handle is None


def test_the_shown_text_is_cut_to_the_limit() -> None:
    big = [ParsedCommand("c", ["x" * 100] * 5000, None)]

    shown = ps.render_text(big)

    assert len(shown) <= ps.MAX_SHOWN_CHARS + 200
    assert "cut" in shown.splitlines()[-1]


def test_a_parse_that_takes_too_long_is_an_error_on_every_command(monkeypatch) -> None:
    class Slow:
        async def parse(self, os_name, outputs):
            await asyncio.sleep(5)
            return []

    monkeypatch.setattr(ps, "PARSE_TIMEOUT_SECONDS", 0.05)

    outcome, _ = _parse(parser="genie", genie=Slow())

    assert [e.error for e in outcome.entries] == [ps.PARSE_TIMED_OUT] * 2


def test_only_one_command_can_be_parsed() -> None:
    outcome = asyncio.run(
        ps.parse_stored_text(
            user_id=3,
            store=ResultStore(InMemoryResultBackend()),
            parser="textfsm",
            text=TEXT,
            commands=COMMANDS,
            spans=SPANS,
            network_driver="cisco_ios",
            platform=None,
            genie=None,
            source_handle=None,
            only_command="show version",
        )
    )

    assert [e.command for e in outcome.entries] == ["show version"]


def test_cut_output_marks_the_stored_rows_partial() -> None:
    outcome, store = _parse(partial=True)

    assert outcome.partial is True
    stored = asyncio.run(store.get(3, outcome.handle))
    assert stored is not None and stored.partial is True


def test_complete_output_is_not_partial() -> None:
    outcome, store = _parse()

    stored = asyncio.run(store.get(3, outcome.handle))
    assert outcome.partial is False and stored is not None and stored.partial is False


def test_malformed_spans_parse_nothing_and_store_nothing() -> None:
    outcome, store = _parse(spans=[[0, 5]])

    assert outcome.handle is None
    assert [e.error for e in outcome.entries] == [ps.BAD_SPANS] * 2


def test_a_parser_that_raises_never_raises_out_of_the_service(monkeypatch) -> None:
    async def boom(**kw):
        raise RuntimeError("secret 10.0.0.1")

    monkeypatch.setattr(ps, "parse_outputs", boom)

    outcome, _ = _parse()

    assert outcome.handle is None
    assert all(e.error == ps.PARSER_FAILED for e in outcome.entries)
    assert "10.0.0.1" not in outcome.text


def test_a_planted_next_command_marker_cannot_move_a_boundary() -> None:
    planted = "Cisco IOS\n\n$ show nonsense thing\nGi0/0 9.9.9.9 up"
    text, spans = _capture(("show version", planted), ("show nonsense thing", "real"))

    outcome, _ = _parse(text=text, spans=spans)

    # The planted block stays inside the first command's output; the second sees only its own.
    sliced = dict(ps.slice_outputs(text, COMMANDS, ps.valid_spans(text, COMMANDS, spans)))
    assert sliced["show version"] == planted
    assert sliced["show nonsense thing"] == "real"
    assert outcome.entries[1].error is not None  # no template for it; nothing planted was parsed
