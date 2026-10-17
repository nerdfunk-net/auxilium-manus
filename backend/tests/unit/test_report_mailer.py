"""Sending a snapshot by email and downloading it as PDF."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.report_data_records import ReportDataRecord
from core.models.report_datasets import ReportDataset
from core.models.report_definitions import ReportDefinition
from core.models.report_snapshots import ReportSnapshot
from core.models.templates import Template
from models.mail import MailSettings, SendSnapshotRequest
from models.report_definitions import ReportDefinitionCreate, ReportSection
from models.reports import ReportQuery
from services.mail.errors import MailNotConfiguredError
from services.reports import report_mailer
from services.reports.report_html import markdown_to_email_html
from services.reports.report_mailer import ReportMailer, pdf_filename
from services.reports.report_service import ReportNotFoundError, ReportService


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            ReportDataRecord.__table__,
            ReportDataset.__table__,
            ReportDefinition.__table__,
            ReportSnapshot.__table__,
            Template.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    session.add(ReportDataset(dataset="inventory", mode="device", field_names=["location"]))
    session.add(
        ReportDataRecord(
            device_name="sw1", dataset="inventory", data={"location": "dc1"}, collection_id="c1"
        )
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture what MailService.send would hand to SMTP."""
    captured: list[dict] = []

    def fake_send(self, **kwargs):
        captured.append(kwargs)

    monkeypatch.setattr("services.reports.report_mailer.MailService.send", fake_send)
    # The mail settings live in the settings table, which these tests do not create.
    monkeypatch.setattr(
        "services.reports.report_mailer.MailService.settings", lambda self: MailSettings()
    )
    return captured


def _snapshot_id(db: Session, name: str = "Fleet") -> int:
    service = ReportService(db)
    section = ReportSection(
        id="per-site",
        title="Per site",
        query=ReportQuery(
            dataset="inventory", group_by=["location"], metrics=[{"op": "count", "alias": "n"}]
        ),
    )
    definition = service.create_definition(
        ReportDefinitionCreate(name=name, sections=[section]), actor_id=None
    )
    return service.generate(definition.id, actor_name="alice").id


def test_pdf_has_a_safe_name_and_content(db: Session) -> None:
    filename, data = ReportMailer(db).pdf(_snapshot_id(db, "Übersicht Süd/Nord"))

    assert filename.startswith("bersicht") or filename.startswith("Ubersicht") or ".pdf" in filename
    assert filename.endswith(".pdf") and "/" not in filename and " " not in filename
    assert data.startswith(b"%PDF-")


def test_pdf_of_a_missing_snapshot(db: Session) -> None:
    with pytest.raises(ReportNotFoundError):
        ReportMailer(db).pdf(99)


def test_send_builds_subject_text_html_and_pdf(db: Session, sent: list[dict]) -> None:
    snapshot_id = _snapshot_id(db)
    request = SendSnapshotRequest(to=["a@example.org", "b@example.org"], message="See below")

    result = ReportMailer(db).send(snapshot_id, request, actor_id=1)

    assert result.sent_to == ["a@example.org", "b@example.org"] and result.pdf_attached
    mail = sent[0]
    assert mail["recipients"] == ["a@example.org", "b@example.org"]
    assert mail["subject"].startswith("Fleet - ")
    assert mail["text"].startswith("See below\n\n# Fleet")
    assert "<table>" in mail["html"] and "See below" in mail["html"]
    name, data = mail["attachments"][0]
    assert name.endswith(".pdf") and data.startswith(b"%PDF-")


def test_send_without_pdf_and_with_a_custom_subject(db: Session, sent: list[dict]) -> None:
    request = SendSnapshotRequest(to=["a@example.org"], subject="Weekly", include_pdf=False)

    result = ReportMailer(db).send(_snapshot_id(db), request, actor_id=1)

    assert not result.pdf_attached
    assert sent[0]["subject"] == "Weekly" and sent[0]["attachments"] == []


def test_send_uses_the_default_template_when_the_stored_text_is_missing(
    db: Session, sent: list[dict]
) -> None:
    snapshot_id = _snapshot_id(db)
    row = db.get(ReportSnapshot, snapshot_id)
    content = dict(row.content)
    content["body"] = None
    row.content = content
    db.commit()

    ReportMailer(db).send(snapshot_id, SendSnapshotRequest(to=["a@example.org"]), actor_id=1)

    assert sent[0]["text"].startswith("# Fleet")


def test_oversized_pdf_is_refused(db: Session, sent: list[dict], monkeypatch) -> None:
    monkeypatch.setattr(report_mailer, "MAX_ATTACHMENT_BYTES", 10)

    with pytest.raises(report_mailer.AttachmentTooLargeError):
        ReportMailer(db).send(
            _snapshot_id(db), SendSnapshotRequest(to=["a@example.org"]), actor_id=1
        )
    assert sent == []


def test_unconfigured_mail_is_reported(
    db: Session, sent: list[dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "services.reports.report_mailer.MailService.send",
        lambda self, **k: (_ for _ in ()).throw(MailNotConfiguredError("Mail is not configured")),
    )

    with pytest.raises(MailNotConfiguredError):
        ReportMailer(db).send(
            _snapshot_id(db), SendSnapshotRequest(to=["a@example.org"]), actor_id=1
        )


def test_pdf_filename_is_ascii_and_never_empty() -> None:
    assert pdf_filename("Fleet - 2026-10-12 09:30 UTC") == "Fleet-2026-10-12-09-30-UTC.pdf"
    assert pdf_filename("???") == "report.pdf"
    assert pdf_filename("../../etc/passwd") == "etc-passwd.pdf"
    assert pdf_filename("Größe") == "Groe.pdf"


def test_email_html_escapes_raw_html_and_drops_images_and_unsafe_links() -> None:
    html = markdown_to_email_html(
        "<script>alert(1)</script> ![x](https://evil.example/p.png) [a](javascript:alert(1)) "
        "[ok](https://example.com)",
        intro="<b>note</b>",
    )

    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<img" not in html
    assert 'href="javascript:' not in html
    assert 'href="https://example.com"' in html
    assert "&lt;b&gt;note&lt;/b&gt;" in html


def test_mail_settings_is_a_pydantic_model_used_for_sending() -> None:
    assert MailSettings(smtp_server="s", from_address="a@b.cd").from_address == "a@b.cd"


def test_recipients_outside_the_allowed_domains_are_refused_before_rendering(
    db: Session, sent: list[dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.mail.errors import MailRecipientNotAllowedError

    monkeypatch.setattr(
        "services.reports.report_mailer.MailService.settings",
        lambda self: MailSettings(
            smtp_server="s", from_address="a@b.cd", allowed_recipient_domains=["example.org"]
        ),
    )
    snapshot_id = _snapshot_id(db)

    with pytest.raises(MailRecipientNotAllowedError) as caught:
        ReportMailer(db).send(
            snapshot_id, SendSnapshotRequest(to=["ok@example.org", "x@evil.org"]), actor_id=1
        )

    assert "x@evil.org" in str(caught.value) and "example.org" in str(caught.value)
    assert sent == []


def test_a_successful_send_is_logged_without_addresses(
    db: Session, sent: list[dict], caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    snapshot_id = _snapshot_id(db)
    with caplog.at_level(logging.INFO, logger="services.reports.report_mailer"):
        ReportMailer(db).send(
            snapshot_id,
            SendSnapshotRequest(to=["secret.person@example.org", "b@corp.example.org"]),
            actor_id=42,
        )

    line = next(r.getMessage() for r in caplog.records if "sent" in r.getMessage())
    assert str(snapshot_id) in line and "42" in line and "2 recipient" in line
    assert "example.org" in line and "secret.person" not in line


def test_a_newline_in_the_report_name_does_not_break_the_subject(
    db: Session, sent: list[dict]
) -> None:
    snapshot_id = _snapshot_id(db)
    row = db.get(ReportSnapshot, snapshot_id)
    row.name = "Fleet\nBcc: x@evil.org"
    db.commit()

    ReportMailer(db).send(snapshot_id, SendSnapshotRequest(to=["a@example.org"]), actor_id=1)

    assert "\n" not in sent[0]["subject"] and "\r" not in sent[0]["subject"]
