"""The signed confirmation token for a proposed report (nothing is generated before the click)."""

from __future__ import annotations

import base64
import json
import time

import pytest

from models.report_definitions import ReportDefinitionCreate, ReportSection
from models.reports import ReportQuery
from services.ai_assistant.report_run_token import (
    TOKEN_TTL_SECONDS,
    InvalidReportTokenError,
    issue_report_token,
    verify_report_token,
)

REPORT = ReportDefinitionCreate(
    name="Serial numbers",
    description="All serials",
    sections=[
        ReportSection(
            id="serials",
            title="Serials",
            query=ReportQuery(
                source="nautobot", dataset="devices", select=["device_name", "serial"]
            ),
        )
    ],
    template_id=4,
)


def _issue(**kw):
    return issue_report_token(**{"user_id": 7, "report": REPORT, **kw})


def test_round_trip_returns_the_same_report() -> None:
    token, expires = _issue()
    grant = verify_report_token(token, user_id=7)
    assert grant.report == REPORT
    assert grant.expires_at == expires
    assert grant.user_id == 7


def test_another_user_cannot_use_the_token() -> None:
    token, _ = _issue()
    with pytest.raises(InvalidReportTokenError):
        verify_report_token(token, user_id=8)


def test_expired_token() -> None:
    token, _ = _issue(now=time.time() - TOKEN_TTL_SECONDS - 1)
    with pytest.raises(InvalidReportTokenError):
        verify_report_token(token, user_id=7)


def test_tampered_payload_is_rejected() -> None:
    token, _ = _issue()
    encoded, signature = token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(encoded))
    payload["r"]["name"] = "Other"
    forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(InvalidReportTokenError):
        verify_report_token(f"{forged}.{signature}", user_id=7)


@pytest.mark.parametrize("bad", [None, 5, "", "x", "a.b.c", "!!.??", "a" * 70000])
def test_malformed_tokens(bad: object) -> None:
    with pytest.raises(InvalidReportTokenError):
        verify_report_token(bad, user_id=7)


def test_a_signed_payload_that_is_not_a_valid_report_is_rejected(monkeypatch) -> None:
    # A correct signature over a report the models refuse (e.g. made by an older version).
    from services.ai_assistant import report_run_token as module

    token, _ = _issue()
    encoded, _ = token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(encoded))
    payload["r"]["sections"][0]["query"]["limit"] = 0
    body = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).decode()
    signature = base64.urlsafe_b64encode(module._sign(body.encode())).decode()
    with pytest.raises(InvalidReportTokenError):
        verify_report_token(f"{body}.{signature}", user_id=7)


@pytest.mark.parametrize("kind", ["workflow_run", "report_run"])
def test_a_chat_with_a_run_card_can_be_saved(kind: str) -> None:
    # The conversation store keeps a proposal's kind and summary; a card kind the whitelist
    # lacks makes saving the whole chat fail.
    from models.ai_conversations import StoredProposal

    assert StoredProposal(kind=kind, summary="x").kind == kind  # type: ignore[arg-type]
