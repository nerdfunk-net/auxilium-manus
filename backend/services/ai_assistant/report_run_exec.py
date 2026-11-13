"""Generate the report a user confirmed on an Ask the Net card (doc/AI_TOOL_CHAIN.md §53).

The report comes from the signed token (``report_run_token``), not from the request, so the user
gets exactly what the card showed. It runs as the user: sources that read an external system
(Nautobot) check that user's permission, and the snapshot is recorded under their name. The work
is blocking (database, and Nautobot through the report source), so callers run ``execute`` in a
worker thread.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from sqlalchemy.orm import Session

from core.database import SessionLocal
from services.ai_assistant.report_run_token import verify_report_token
from services.reports.report_service import ReportService


@dataclass(frozen=True)
class GeneratedReport:
    snapshot_id: int
    name: str
    status: str
    sections_failed: int


class ReportRunExecutor:
    def __init__(
        self, session_factory: Callable[[], AbstractContextManager[Session]] = SessionLocal
    ) -> None:
        self._session_factory = session_factory

    def execute(self, *, user_id: int, actor_name: str, token: object) -> GeneratedReport:
        """Verify the token and generate its report. Raises ``InvalidReportTokenError`` for a
        bad token and ``InvalidReportError`` when the report cannot be generated at all (an
        unknown source, an inactive template); a failing section only makes the snapshot partial."""
        grant = verify_report_token(token, user_id=user_id)
        with self._session_factory() as db:
            snapshot = ReportService(db, actor_user_id=user_id).generate_adhoc(
                grant.report, actor_name=actor_name
            )
            failed = sum(1 for section in snapshot.content["sections"] if section["status"] != "ok")
            return GeneratedReport(
                snapshot_id=snapshot.id,
                name=snapshot.name,
                status=snapshot.status,
                sections_failed=failed,
            )
