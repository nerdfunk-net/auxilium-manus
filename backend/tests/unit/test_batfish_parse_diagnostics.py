"""``BatfishPreviewService.run_parse_diagnostics``: the three parse questions of one snapshot.

BatfishService is mocked; nothing here talks to a coordinator.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.batfish.common.exceptions import BatfishAPIError
from services.batfish.credentials import BatfishConnection
from services.batfish.preview_service import BatfishPreviewService


def _service() -> tuple[BatfishPreviewService, MagicMock]:
    sources = MagicMock()
    sources.resolve_connection.return_value = BatfishConnection(host="batfish", port=9996)
    batfish = MagicMock()
    batfish.list_networks = AsyncMock(return_value=["net"])
    batfish.file_parse_status = AsyncMock(return_value=[{"File_Name": "a", "Status": "FAILED"}])
    batfish.parse_warning = AsyncMock(return_value=[{"Filename": "a", "Comment": "c"}])
    batfish.init_issues = AsyncMock(return_value=[{"Type": "t"}])
    return BatfishPreviewService(sources, batfish), batfish


class ParseDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_all_three_questions_on_the_named_snapshot(self) -> None:
        service, batfish = _service()

        result = await service.run_parse_diagnostics("lab", "net", " run-7 ")

        self.assertEqual(result.snapshot, "run-7")
        self.assertEqual(result.file_status, [{"File_Name": "a", "Status": "FAILED"}])
        self.assertEqual(result.warnings, [{"Filename": "a", "Comment": "c"}])
        self.assertEqual(result.issues, [{"Type": "t"}])
        self.assertEqual(result.unavailable, {})
        for method in (batfish.file_parse_status, batfish.parse_warning, batfish.init_issues):
            self.assertEqual(method.await_args.kwargs["snapshot"], "run-7")

    async def test_defaults_to_the_newest_snapshot(self) -> None:
        service, batfish = _service()
        batfish.list_snapshots_with_metadata = AsyncMock(
            return_value=[
                {"name": "old", "metadata": {"creationTimestamp": "2026-01-01T00:00:00Z"}},
                {"name": "new", "metadata": {"creationTimestamp": "2026-02-01T00:00:00Z"}},
            ]
        )

        result = await service.run_parse_diagnostics("lab", "net", None)

        self.assertEqual(result.snapshot, "new")

    async def test_one_failing_question_is_reported_not_raised(self) -> None:
        service, batfish = _service()
        batfish.init_issues = AsyncMock(side_effect=BatfishAPIError("boom"))

        result = await service.run_parse_diagnostics("lab", "net", "run-7")

        self.assertEqual(result.issues, [])
        self.assertEqual(list(result.unavailable), ["issues"])
        self.assertEqual(len(result.file_status), 1)

    async def test_a_section_cut_at_the_row_cap_is_named(self) -> None:
        from models.batfish import MAX_PREVIEW_ROWS

        service, batfish = _service()
        batfish.parse_warning = AsyncMock(
            return_value=[{"Filename": "a", "Comment": "c"}] * (MAX_PREVIEW_ROWS + 1)
        )

        result = await service.run_parse_diagnostics("lab", "net", "run-7")

        self.assertEqual(len(result.warnings), MAX_PREVIEW_ROWS)
        self.assertEqual(result.truncated_sections, ("warnings",))
        self.assertTrue(result.truncated)

    async def test_nothing_is_named_when_no_section_was_cut(self) -> None:
        service, _ = _service()

        result = await service.run_parse_diagnostics("lab", "net", "run-7")

        self.assertEqual(result.truncated_sections, ())
        self.assertFalse(result.truncated)

    async def test_all_questions_failing_raises(self) -> None:
        service, batfish = _service()
        for name in ("file_parse_status", "parse_warning", "init_issues"):
            setattr(batfish, name, AsyncMock(side_effect=BatfishAPIError("boom")))

        with self.assertRaises(BatfishAPIError):
            await service.run_parse_diagnostics("lab", "net", "run-7")

    async def test_unknown_network_is_refused_before_any_question(self) -> None:
        service, batfish = _service()

        with self.assertRaises(ValueError):
            await service.run_parse_diagnostics("lab", "typo", "run-7")
        batfish.file_parse_status.assert_not_awaited()


class ClientQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_questions_dispatch_by_name_without_params(self) -> None:
        from services.batfish.client import BatfishService

        service = BatfishService()
        service._answer = AsyncMock(return_value=[])  # type: ignore[method-assign]
        conn = BatfishConnection(host="batfish", port=9996)

        await service.parse_warning(conn, batfish_network="n", snapshot="s")
        await service.init_issues(conn, batfish_network="n", snapshot="s")

        names = [c.args[3] for c in service._answer.await_args_list]
        self.assertEqual(names, ["parseWarning", "initIssues"])
        self.assertTrue(all(c.args[4] == {} for c in service._answer.await_args_list))
