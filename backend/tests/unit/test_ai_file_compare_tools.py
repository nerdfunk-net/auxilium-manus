"""Tests for the file/Nautobot comparison tools (doc/AI_TOOL_CHAIN.md §61)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import ValidationError

from services.ai_assistant import file_compare_reader as fc
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.tools import file_compare_tools as tools
from services.ai_assistant.tools.base import ToolContext
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY
from services.csv_lookup import CsvRow, ValueItem, reconcile

SECRET_SERIAL = "SN-LEAK-777"


def _outcome(
    rows: list[CsvRow] | None = None,
    items: list[ValueItem] | None = None,
    *,
    contains: bool = False,
) -> fc.CompareOutcome:
    rows = (
        rows
        if rows is not None
        else [
            CsvRow(key=SECRET_SERIAL, values={"data": "file-only"}),
            CsvRow(key="BOTH", values={"data": "x"}),
        ]
    )
    items = (
        items
        if items is not None
        else [
            ValueItem("1", "BOTH", {"name": "dev1", "location": "Berlin"}),
            ValueItem("2", "NB-ONLY-555", {"name": "dev2", "location": "Rome"}),
            ValueItem("3", None, {"name": "dev3", "location": "Rome"}),
        ]
    )
    request = fc.CompareRequest(
        repository=None,
        file="compare.csv",
        key_column="serial",
        field="serial",
        match_mode="contains" if contains else "match",
        case_insensitive=False,
        delimiter=None,
        filters={},
    )
    return fc.CompareOutcome(
        repository="Gitea CSV",
        file="data/compare.csv",
        request=request,
        reconciliation=reconcile(rows, items, contains=contains),
        applied_filters={"location": "Berlin"},
    )


class FakeReader:
    def __init__(self, outcome: fc.CompareOutcome | Exception | None = None) -> None:
        self.outcome = outcome if outcome is not None else _outcome()
        self.requests: list[fc.CompareRequest] = []
        self.repositories = [fc.CompareRepository("Gitea CSV", "main", "csv_imports", None)]

    async def list_repositories(self) -> list[fc.CompareRepository]:
        return self.repositories

    async def compare(self, request: fc.CompareRequest) -> fc.CompareOutcome:
        self.requests.append(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _ctx(reader: Any, *, content: bool = False, store: bool = True, everything: bool = False):
    extras: dict[str, Any] = {tools.FILE_COMPARE_READER_KEY: reader}
    if store:
        extras[RESULT_STORE_KEY] = ResultStore(InMemoryResultBackend())
    sharing = (
        SharingPolicy(inventory=True, addresses=True, content=True)
        if everything
        else SharingPolicy(content=content)
    )
    return ToolContext(user_id=7, redactor=Redactor(), extras=extras, sharing=sharing)


def _call(name: str, ctx: ToolContext, **kwargs: Any):
    tool = next(t for t in tools.build_file_compare_tools() if t.name == name)
    return asyncio.run(tool.handler(ctx, tool.input_model(**kwargs)))


ARGS = {"file": "compare.csv", "key_column": "serial", "nautobot_field": "serial"}


def test_the_answer_has_counts_and_no_value() -> None:
    ctx = _ctx(FakeReader(), everything=True)  # even with every switch on
    out = _call("compare_file_with_nautobot", ctx, **ARGS)
    assert SECRET_SERIAL not in out.content and "NB-ONLY-555" not in out.content
    assert "dev2" not in out.content and "file-only" not in out.content
    data = json.loads(out.content)
    assert data["counts"] == {
        "file_rows": 2,
        "rows_without_key": 0,
        "devices": 3,
        "devices_without_value": 1,
        "matched_keys": 1,
        "matched_devices": 1,
        "matched_pairs": 1,
        "only_in_file": 1,
        "only_in_nautobot": 1,
        "duplicate_keys": 0,
        "duplicate_device_values": 0,
        "devices_matching_several_keys": 0,
        "short_keys": 0,
    }
    assert data["repository"] == "Gitea CSV" and data["file"] == "data/compare.csv"
    assert data["applied_filters"] == {"location": "Berlin"}
    assert "card" in data["note"]


def test_the_card_proposal_carries_the_handle_and_counts_only() -> None:
    ctx = _ctx(FakeReader())
    out = _call("compare_file_with_nautobot", ctx, **ARGS)
    proposal = out.proposal
    assert proposal is not None and proposal["kind"] == "compare_result"
    assert proposal["handle"].startswith("res_")
    assert proposal["counts"]["only_in_file"] == 1
    assert proposal["inline_limit"] == tools.INLINE_ROWS_PER_SIDE
    assert SECRET_SERIAL not in json.dumps(proposal)


def test_the_rows_are_stored_for_the_card_and_hidden_from_the_model() -> None:
    ctx = _ctx(FakeReader())
    out = _call("compare_file_with_nautobot", ctx, **ARGS)
    stored = asyncio.run(ctx.extras[RESULT_STORE_KEY].get(7, out.proposal["handle"]))
    assert stored.kind == "compare_result" and (stored.meta or {})["model_hidden"] is True
    by_side = {}
    for row in stored.rows or []:
        by_side.setdefault(row["side"], []).append(row)
    assert by_side["only_in_file"] == [
        {
            "side": "only_in_file",
            "value": SECRET_SERIAL,
            "device_name": "",
            "device_location": "",
            "device_id": "",
            "file_data": "file-only",
        }
    ]
    assert len(by_side["in_both"]) == 1
    both = by_side["in_both"][0]
    assert both["value"] and both["device_name"] and both["device_id"]
    assert by_side["only_in_nautobot"][0]["device_name"] == "dev2"
    assert by_side["only_in_nautobot"][0]["file_data"] == ""
    assert by_side["without_value"][0]["device_name"] == "dev3"
    assert (stored.meta or {})["repository"] == "Gitea CSV"


def test_the_request_is_passed_on() -> None:
    reader = FakeReader()
    _call(
        "compare_file_with_nautobot",
        _ctx(reader),
        repository="Gitea CSV",
        file="c.csv",
        key_column="id",
        nautobot_field="primary_ip4",
        match_mode="contains",
        case_insensitive=True,
        delimiter=",",
        location="Berlin",
        role="Switch",
    )
    request = reader.requests[0]
    assert (request.repository, request.file, request.key_column) == ("Gitea CSV", "c.csv", "id")
    assert request.field == "primary_ip4" and request.match_mode == "contains"
    assert request.case_insensitive and request.delimiter == ","
    assert request.filters == {
        "location": "Berlin",
        "role": "Switch",
        "status": None,
        "tag": None,
        "device_type": None,
        "platform": None,
    }


def test_warnings_for_the_things_that_make_a_result_unreliable() -> None:
    rows = [CsvRow("1", {}), CsvRow("1", {}), CsvRow("", {}), CsvRow("12", {})]
    items = [ValueItem("a", "X123", {}), ValueItem("b", "X123", {}), ValueItem("c", None, {})]
    out = _call(
        "compare_file_with_nautobot",
        _ctx(FakeReader(_outcome(rows, items, contains=True))),
        **ARGS,
    )
    warnings = " ".join(json.loads(out.content)["warnings"])
    for phrase in ("no value", "no key", "duplicate", "1-2 characters", "several"):
        assert phrase in warnings, phrase


def test_file_columns_and_cells_are_capped_in_the_stored_rows() -> None:
    wide = CsvRow("K", {f"c{i}": "x" * 500 for i in range(30)})
    ctx = _ctx(FakeReader(_outcome([wide], [])))
    out = _call("compare_file_with_nautobot", ctx, **ARGS)
    stored = asyncio.run(ctx.extras[RESULT_STORE_KEY].get(7, out.proposal["handle"]))
    row = stored.rows[0]
    file_columns = [k for k in row if k.startswith("file_")]
    assert len(file_columns) == tools.MAX_FILE_COLUMNS
    assert all(len(row[k]) <= tools.MAX_CELL_CHARS for k in file_columns)


def test_a_result_too_large_for_one_handle_is_cut_and_flagged(monkeypatch) -> None:
    from services.ai_assistant.results import store as store_module

    monkeypatch.setattr(store_module, "MAX_STORED_BYTES", 3000)
    rows = [CsvRow(f"KEY{i:04d}", {"data": "y" * 40}) for i in range(200)]
    ctx = _ctx(FakeReader(_outcome(rows, [])))
    out = _call("compare_file_with_nautobot", ctx, **ARGS)
    data = json.loads(out.content)
    assert data["partial"] is True and "size limit" in " ".join(data["warnings"])
    assert out.proposal["partial"] is True
    stored = asyncio.run(ctx.extras[RESULT_STORE_KEY].get(7, out.proposal["handle"]))
    assert stored.partial and 0 < len(stored.rows) < 200


def test_errors_are_fixed_sentences_and_columns_need_the_content_switch() -> None:
    error = fc.FileCompareError("The key column was not found in the file", columns=("a", "b"))
    without = _call("compare_file_with_nautobot", _ctx(FakeReader(error), content=False), **ARGS)
    assert without.is_error and without.content == "The key column was not found in the file"
    with_content = _call(
        "compare_file_with_nautobot", _ctx(FakeReader(error), content=True), **ARGS
    )
    assert with_content.is_error and "a, b" in with_content.content


def test_a_denied_user_and_a_missing_store() -> None:
    denied = _call(
        "compare_file_with_nautobot", _ctx(FakeReader(fc.FileCompareDeniedError())), **ARGS
    )
    assert denied.is_error and "cannot compare" in denied.content
    reader = FakeReader()
    no_store = _call("compare_file_with_nautobot", _ctx(reader, store=False), **ARGS)
    assert no_store.is_error and reader.requests == []


def test_list_file_repositories() -> None:
    out = _call("list_file_repositories", _ctx(FakeReader()))
    assert json.loads(out.content)["repositories"] == [
        {"name": "Gitea CSV", "branch": "main", "category": "csv_imports", "last_sync": None}
    ]
    denied = _call("list_file_repositories", _ctx(FakeReader(), content=False))
    assert not denied.is_error
    reader = FakeReader()
    reader.list_repositories = _raise(fc.FileCompareDeniedError())  # type: ignore[method-assign]
    assert _call("list_file_repositories", _ctx(reader)).is_error


def _raise(error: Exception):
    async def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    return fail


def test_inputs_are_validated() -> None:
    model = next(
        t for t in tools.build_file_compare_tools() if t.name == "compare_file_with_nautobot"
    ).input_model
    with pytest.raises(ValidationError):
        model(**{**ARGS, "nautobot_field": "comments"})
    with pytest.raises(ValidationError):
        model(**ARGS, extra_field=1)
    with pytest.raises(ValidationError):
        model(**{**ARGS, "file": "a\x00b.csv"})
    with pytest.raises(ValidationError):
        model(**ARGS, match_mode="regex")


def test_the_tool_names_follow_the_naming_rule() -> None:
    names = {t.name for t in tools.build_file_compare_tools()}
    assert names == {"list_file_repositories", "compare_file_with_nautobot"}
    assert not any(n.startswith(("run", "trigger", "execute", "start", "delete")) for n in names)


# -- the general surface ---------------------------------------------------------------------


def _session(**overrides: Any):
    from services.ai_assistant.surfaces import build_general_session
    from tests.unit.test_ai_batfish_tools import FakeReader as BatfishFake

    base: dict[str, Any] = {
        "user_id": 7,
        "reader": BatfishFake(),
        "store": ResultStore(InMemoryResultBackend()),
        "sharing": SharingPolicy(),  # no data switch on
        "may_query_batfish": False,
        "file_compare_reader": FakeReader(),
    }
    base.update(overrides)
    return build_general_session(**base)


def test_the_surface_offers_the_tools_without_any_data_switch_or_batfish() -> None:
    session = _session()
    names = {s.name for s in session.toolbox.specs()}
    assert {"list_file_repositories", "compare_file_with_nautobot"} <= names
    assert "compare_file_with_nautobot" in session.system


def test_the_surface_needs_the_reader_and_the_result_store() -> None:
    for overrides in ({"file_compare_reader": None}, {"store": None}):
        names = {s.name for s in _session(**overrides).toolbox.specs()}
        assert "compare_file_with_nautobot" not in names, overrides


def test_the_result_store_is_available_to_the_tool_without_batfish() -> None:
    session = _session()
    out = asyncio.run(
        session.toolbox.execute(
            __import__("services.ai_assistant.providers.base", fromlist=["ToolCall"]).ToolCall(
                id="1", name="compare_file_with_nautobot", input=ARGS
            )
        )
    )
    assert not out.is_error and out.proposal is not None


def test_every_tool_name_is_known_to_the_playbooks() -> None:
    from services.ai_assistant.tools.playbook_tools import known_general_tool_names

    assert {"list_file_repositories", "compare_file_with_nautobot"} <= known_general_tool_names()
