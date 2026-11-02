"""``get_interface_properties`` on a device with hundreds of interfaces: a summary that covers
every interface and a status filter, so the 20-row preview is not the only way in.

A fake reader stands in for the coordinator; nothing here talks to Batfish.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.batfish_shaping import filter_interfaces, summarize_interfaces
from services.ai_assistant.tools.batfish_tools import (
    BATFISH_READER_KEY,
    BatfishAnswer,
    build_batfish_tools,
)
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY, build_result_tools
from tests.unit.test_ai_batfish_tools import FakeReader

ALL = SharingPolicy(inventory=True, addresses=True, content=True)


def _row(
    n: int, *, active: bool | None = True, admin_up: bool = True, mode: str = "ACCESS"
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "Interface": {"hostname": "lab", "interface": f"Gi1/0/{n}"},
        "Admin_Up": admin_up,
        "Switchport_Mode": mode,
        "Primary_Address": f"10.0.{n // 250}.{n % 250}/24" if n % 10 == 0 else None,
    }
    if active is not None:
        row["Active"] = active
    return row


MIXED = [
    _row(1),
    _row(2),
    _row(3, active=False, admin_up=False),  # shut down on purpose
    _row(4, active=False),  # enabled, yet Batfish deactivated it
    _row(5, mode="TRUNK"),
    _row(6, active=None),  # no Active column in the answer
]


def test_summary_counts_every_interface_and_separates_deactivated_ones() -> None:
    summary = summarize_interfaces(MIXED)

    assert summary["total"] == 6
    assert summary["active"] == 3
    assert summary["inactive"] == 2
    assert summary["admin_down"] == 1
    assert summary["inactive_but_admin_up"] == 1
    assert summary["by_switchport_mode"] == {"ACCESS": 5, "TRUNK": 1}


def test_interfaces_without_a_flag_are_counted_so_the_buckets_add_up() -> None:
    summary = summarize_interfaces(MIXED)

    assert summary["active_unknown"] == 1  # Gi1/0/6 has no Active column
    assert summary["active"] + summary["inactive"] + summary["active_unknown"] == summary["total"]
    assert summary["admin_up_unknown"] == 0

    nulls = summarize_interfaces([{"Active": None, "Admin_Up": None}, {"Admin_Up": True}])
    assert (nulls["active_unknown"], nulls["admin_up_unknown"]) == (2, 1)


def test_summary_of_nothing_is_all_zero() -> None:
    summary = summarize_interfaces([])

    assert summary["total"] == 0 and summary["inactive"] == 0
    assert summary["by_switchport_mode"] == {}


def test_filter_by_status_returns_new_lists_and_leaves_the_input_alone() -> None:
    before = [dict(r) for r in MIXED]

    names = {
        status: [r["Interface"]["interface"] for r in filter_interfaces(MIXED, status)]
        for status in ("all", "active", "inactive", "admin_down", "inactive_but_admin_up")
    }

    assert names["all"] == [f"Gi1/0/{n}" for n in range(1, 7)]
    assert names["active"] == ["Gi1/0/1", "Gi1/0/2", "Gi1/0/5"]
    assert names["inactive"] == ["Gi1/0/3", "Gi1/0/4"]
    assert names["admin_down"] == ["Gi1/0/3"]
    assert names["inactive_but_admin_up"] == ["Gi1/0/4"]
    assert MIXED == before


class InterfaceToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.reader = FakeReader()
        self.store = ResultStore(InMemoryResultBackend())

    def _answer(self, rows: list[dict[str, Any]], *, truncated: bool = False) -> None:
        self.reader.answer = BatfishAnswer(
            rows=rows, snapshot="run-2", snapshot_created="t", truncated=truncated
        )

    async def _call(self, **args: Any) -> dict[str, Any]:
        ctx = ToolContext(
            user_id=1,
            redactor=Redactor(),
            extras={BATFISH_READER_KEY: self.reader, RESULT_STORE_KEY: self.store},
            sharing=ALL,
        )
        box = Toolbox([*build_batfish_tools(), *build_result_tools()], ctx)
        out = await box.execute(ToolCall("1", "get_interface_properties", args))
        self.assertFalse(out.is_error, out.content)
        return json.loads(out.content)

    async def test_the_summary_covers_all_interfaces_not_just_the_preview(self) -> None:
        rows = [_row(n, active=n % 4 != 0) for n in range(400)]
        self._answer(rows)

        data = await self._call(network="net1", nodes=["lab"])

        assert len(data["rows"]) == 20
        assert data["total_rows"] == 400
        assert data["summary"]["total"] == 400
        assert data["summary"]["inactive"] == 100
        assert data["summary"]["active"] == 300
        assert data["summary_complete"] is True

    async def test_a_status_filter_shows_only_those_interfaces(self) -> None:
        self._answer(MIXED)

        data = await self._call(network="net1", status="inactive_but_admin_up")

        assert [r["Interface"] for r in data["rows"]] == ["Gi1/0/4"]
        assert data["total_rows"] == 1
        assert data["summary"]["total"] == 6  # the summary still describes the whole device
        assert "1 of 6" in data["note"]

    async def test_a_filter_with_no_match_says_so_instead_of_an_empty_table(self) -> None:
        self._answer([_row(1), _row(2)])

        data = await self._call(network="net1", status="inactive")

        assert data["rows"] == []
        assert data["summary"]["total"] == 2
        assert "0 of 2" in data["note"]

    async def test_the_filtered_rows_are_what_the_handle_holds(self) -> None:
        self._answer([_row(n, active=n % 2 == 0) for n in range(200)])

        data = await self._call(network="net1", status="inactive")

        assert data["total_rows"] == 100
        assert data["handle"]

    async def test_the_default_status_changes_nothing_for_a_small_device(self) -> None:
        self._answer(MIXED)

        data = await self._call(network="net1")

        assert len(data["rows"]) == 6
        assert "note" not in data or "of 6" not in data["note"]

    async def test_a_cut_answer_marks_the_summary_as_a_lower_bound(self) -> None:
        self._answer(MIXED, truncated=True)

        data = await self._call(network="net1")

        assert data["summary_complete"] is False

    async def test_unknown_status_is_rejected(self) -> None:
        ctx = ToolContext(
            user_id=1,
            redactor=Redactor(),
            extras={BATFISH_READER_KEY: self.reader},
            sharing=ALL,
        )
        out = await Toolbox(build_batfish_tools(), ctx).execute(
            ToolCall("1", "get_interface_properties", {"network": "n", "status": "broken"})
        )

        assert out.is_error
        assert self.reader.calls == []
