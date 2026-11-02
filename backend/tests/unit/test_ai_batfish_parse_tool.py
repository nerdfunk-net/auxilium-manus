"""``get_snapshot_parse_issues``: opt-in, sections, notes, errors. A fake reader stands in for
the coordinator; nothing here talks to Batfish, the database or Redis."""

from __future__ import annotations

import json
import unittest
from typing import Any

from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.batfish_tools import (
    BATFISH_READER_KEY,
    BatfishAccessError,
    BatfishInputError,
    BatfishUnavailableError,
    SnapshotDiagnostics,
    build_batfish_tools,
)
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
NO_CONTENT = SharingPolicy(inventory=True, addresses=True)

DIAGNOSTICS = SnapshotDiagnostics(
    snapshot="run-2",
    snapshot_created="2026-11-01T10:00:00Z",
    file_status=[
        {"File_Name": "r1.cfg", "Status": "PASSED", "File_Format": "CISCO_IOS", "Nodes": ["r1"]},
        {
            "File_Name": "r2.cfg",
            "Status": "PARTIALLY_UNRECOGNIZED",
            "File_Format": "CISCO_IOS",
            "Nodes": ["r2"],
        },
    ],
    warnings=[
        {"Filename": "r2.cfg", "Line": 5, "Text": "secret-ish line", "Comment": "unrecognized"}
    ],
    issues=[],
)


class FakeReader:
    def __init__(self) -> None:
        self.diagnostics = DIAGNOSTICS
        self.error: Exception | None = None
        self.calls: list[tuple[Any, ...]] = []

    async def list_sources(self) -> list[str]:
        return ["lab"]

    async def snapshot_diagnostics(
        self, source_id: str, network: str, snapshot: str | None
    ) -> SnapshotDiagnostics:
        self.calls.append((source_id, network, snapshot))
        if self.error:
            raise self.error
        return self.diagnostics


class ParseIssuesToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.reader = FakeReader()
        self.store = ResultStore(InMemoryResultBackend())

    async def _call(self, sharing: SharingPolicy = ALL, **args: Any) -> tuple[ToolOutput, Any]:
        ctx = ToolContext(
            user_id=7,
            redactor=Redactor(),
            extras={BATFISH_READER_KEY: self.reader, RESULT_STORE_KEY: self.store},
            sharing=sharing,
        )
        out = await Toolbox(build_batfish_tools(), ctx).execute(
            ToolCall(id="1", name="get_snapshot_parse_issues", input=args)
        )
        try:
            return out, json.loads(out.content)
        except ValueError:
            return out, None

    async def test_reports_problems_with_summary_and_snapshot(self) -> None:
        out, data = await self._call(network="net1")

        self.assertFalse(out.is_error)
        self.assertEqual(self.reader.calls, [("lab", "net1", None)])
        self.assertEqual(data["snapshot"], "run-2")
        self.assertEqual(data["snapshot_created"], "2026-11-01T10:00:00Z")
        self.assertEqual(data["summary"]["files_by_status"]["PARTIALLY_UNRECOGNIZED"], 1)
        sections = {row["Section"] for row in data["rows"]}
        self.assertEqual(sections, {"file", "warning"})

    async def test_config_text_needs_the_content_opt_in(self) -> None:
        _, with_content = await self._call(ALL, network="net1")
        _, without = await self._call(NO_CONTENT, network="net1")

        self.assertIn("secret-ish line", json.dumps(with_content))
        self.assertNotIn("secret-ish line", json.dumps(without))
        self.assertIn("not shown", json.dumps(without).lower())

    async def test_not_shared_without_the_addresses_opt_in(self) -> None:
        out, data = await self._call(SharingPolicy(inventory=True), network="net1")

        self.assertEqual(self.reader.calls, [])
        self.assertIn("not_shared", json.dumps(data))
        self.assertFalse(out.is_error)

    async def test_section_and_include_passed_are_forwarded_to_shaping(self) -> None:
        _, data = await self._call(network="net1", section="files", include_passed=True)

        self.assertEqual({r["Section"] for r in data["rows"]}, {"file"})
        self.assertEqual(len(data["rows"]), 2)

    async def test_clean_snapshot_says_so_and_does_not_claim_more(self) -> None:
        self.reader.diagnostics = SnapshotDiagnostics(
            snapshot="run-2",
            snapshot_created=None,
            file_status=[{"File_Name": "r1.cfg", "Status": "PASSED", "Nodes": ["r1"]}],
            warnings=[],
            issues=[],
        )

        _, data = await self._call(network="net1")

        self.assertEqual(data["rows"], [])
        text = json.dumps(data).lower()
        self.assertIn("no parse problems", text)
        self.assertIn("inactive", text)

    async def test_counts_cut_at_the_row_cap_are_marked_as_lower_bounds(self) -> None:
        self.reader.diagnostics = SnapshotDiagnostics(
            snapshot="run-2",
            snapshot_created=None,
            file_status=DIAGNOSTICS.file_status,
            warnings=DIAGNOSTICS.warnings,
            issues=[],
            truncated=True,
            truncated_sections=("warnings",),
        )

        _, data = await self._call(network="net1")

        self.assertIs(data["summary_complete"], False)
        self.assertEqual(data["summary_cut_sections"], ["warnings"])
        self.assertIn("at least", data["note"])
        self.assertIn("warnings", data["note"])

    async def test_a_complete_answer_says_its_summary_is_complete(self) -> None:
        _, data = await self._call(network="net1")

        self.assertIs(data["summary_complete"], True)
        self.assertNotIn("summary_cut_sections", data)

    async def test_unavailable_section_is_named(self) -> None:
        self.reader.diagnostics = SnapshotDiagnostics(
            snapshot="run-2",
            snapshot_created=None,
            file_status=DIAGNOSTICS.file_status,
            warnings=[],
            issues=[],
            unavailable={"issues": "BatfishAPIError"},
        )

        _, data = await self._call(network="net1")

        self.assertEqual(data["unavailable_sections"], ["issues"])
        self.assertIn("issues", json.dumps(data["note"]))

    async def test_reader_errors_become_safe_tool_errors(self) -> None:
        for exc, fragment in (
            (BatfishInputError("Unknown network"), "Unknown network"),
            (BatfishAccessError(), "not available"),
            (BatfishUnavailableError(), "not reachable"),
        ):
            self.reader.error = exc
            out, _ = await self._call(network="net1")
            self.assertTrue(out.is_error)
            self.assertIn(fragment, out.content)

    async def test_input_is_bounded(self) -> None:
        for bad in (
            {"network": "n", "section": "everything"},
            {"network": "n", "unexpected": 1},
            {"network": ""},
        ):
            out, _ = await self._call(**bad)
            self.assertTrue(out.is_error, bad)
        self.assertEqual(self.reader.calls, [])
