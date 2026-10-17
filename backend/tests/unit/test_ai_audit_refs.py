"""The turn audit line carries the ids the tools touched, never names or content."""

from __future__ import annotations

import logging

from services.ai_assistant.audit import AuditContext, TurnAudit
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.base import Toolbox, ToolContext


def test_refs_are_logged_as_ids_only(caplog) -> None:
    ctx = ToolContext(user_id=7, redactor=Redactor())
    ctx.audit_refs.update({"run:12", "artifact:abc-1", "inventory:3"})
    turn = TurnAudit(AuditContext(user_id=7, surface="run_viewer", provider="p", model="m"))
    turn.refs = set(Toolbox((), ctx).audit_refs)

    with caplog.at_level(logging.INFO, logger="ai_assistant.audit"):
        turn.log()

    line = caplog.records[-1].getMessage()
    assert "refs=artifact:abc-1,inventory:3,run:12" in line


def test_no_refs_logs_a_dash(caplog) -> None:
    turn = TurnAudit(AuditContext(user_id=7, surface="plain", provider="p", model="m"))
    with caplog.at_level(logging.INFO, logger="ai_assistant.audit"):
        turn.log()
    assert "refs=-" in caplog.records[-1].getMessage()
