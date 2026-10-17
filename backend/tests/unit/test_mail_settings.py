"""Global mail settings, message building and the SMTP sender."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import aiosmtplib
import pytest
from pydantic import ValidationError

from models.mail import MailSettings, SendSnapshotRequest
from services.mail import smtp_sender
from services.mail.errors import MailNotConfiguredError, MailSendError
from services.mail.mail_settings_service import MailSettingsService


class FakeSettingsRepo:
    """In-memory stand-in for SettingsRepository (the settings table uses JSONB)."""

    rows: dict[str, SimpleNamespace] = {}

    def __init__(self, db) -> None:
        pass

    def get_by_key(self, key):
        return self.rows.get(key)

    def create(self, *, key, value, description):
        self.rows[key] = SimpleNamespace(key=key, value=value)
        return self.rows[key]

    def update(self, row, fields):
        row.value = fields["value"]
        return row


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch):
    FakeSettingsRepo.rows = {}
    monkeypatch.setattr("services.mail.mail_settings_service.SettingsRepository", FakeSettingsRepo)
    return object()


def _configured(**overrides) -> MailSettings:
    values = {"smtp_server": "smtp.example.org", "from_address": "reports@example.org"}
    values.update(overrides)
    return MailSettings(**values)


# -- models --------------------------------------------------------------------------------


def test_defaults_are_secure_and_unconfigured() -> None:
    settings = MailSettings()

    assert (settings.security, settings.verify_tls, settings.smtp_port) == ("starttls", True, 587)
    assert settings.smtp_server == "" and settings.credential_name is None


def test_a_credential_needs_an_encrypted_connection() -> None:
    with pytest.raises(ValidationError):
        MailSettings(security="none", credential_name="smtp-user")
    assert MailSettings(security="ssl", credential_name="smtp-user").credential_name == "smtp-user"
    assert MailSettings(security="none").credential_name is None


@pytest.mark.parametrize("server", ["smtp example.org", "smtp.example.org/path", "a b"])
def test_server_must_be_a_plain_host(server: str) -> None:
    with pytest.raises(ValidationError):
        MailSettings(smtp_server=server)


def test_unknown_fields_and_bad_ports_are_rejected() -> None:
    for bad in ({"x": 1}, {"smtp_port": 0}, {"smtp_port": 70000}, {"security": "tls"}):
        with pytest.raises(ValidationError):
            MailSettings(**bad)


def test_from_address_must_be_a_bare_address() -> None:
    assert MailSettings(from_address=" Reports <reports@example.org> ").from_address == (
        "reports@example.org"
    )
    for bad in ("not-an-address", "a@b\nBcc: x@y"):
        with pytest.raises(ValidationError):
            MailSettings(from_address=bad)


def test_send_request_cleans_recipients_and_subject() -> None:
    request = SendSnapshotRequest(
        to=["A <a@example.org>", "b@example.org", "a@example.org"], subject="  Weekly  "
    )

    assert request.to == ["a@example.org", "b@example.org"]
    assert request.subject == "Weekly"
    for bad in (
        {"to": []},
        {"to": ["nope"]},
        {"to": ["a@b.c"], "subject": "x\nBcc: y@z.de"},
        {"to": [f"u{i}@example.org" for i in range(21)]},
        {"to": ["a@b.c"], "extra": 1},
    ):
        with pytest.raises(ValidationError):
            SendSnapshotRequest(**bad)


# -- settings service ----------------------------------------------------------------------


def test_settings_default_then_round_trip(db) -> None:
    service = MailSettingsService(db)
    assert service.get().configured is False

    saved = service.update(_configured(credential_name="smtp-user"))
    again = MailSettingsService(db).get()

    assert saved.configured and again.configured
    assert again.smtp_server == "smtp.example.org"
    assert again.credential_name == "smtp-user"
    service.update(_configured(smtp_port=465, security="ssl"))
    assert MailSettingsService(db).load().smtp_port == 465


# -- message and sender --------------------------------------------------------------------


def test_build_message_has_text_html_and_a_pdf_attachment() -> None:
    message = smtp_sender.build_message(
        sender="reports@example.org",
        recipients=["a@example.org", "b@example.org"],
        subject="Fleet",
        text="plain",
        html="<p>html</p>",
        attachments=[("fleet.pdf", b"%PDF-1.4 x")],
    )

    assert message["To"] == "a@example.org, b@example.org"
    kinds = [part.get_content_type() for part in message.walk()]
    assert "text/plain" in kinds and "text/html" in kinds and "application/pdf" in kinds
    attachment = next(message.iter_attachments())
    assert attachment.get_filename() == "fleet.pdf"


def test_send_message_passes_the_settings_to_aiosmtplib(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    async def fake_send(message, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(aiosmtplib, "send", fake_send)
    message = smtp_sender.build_message(
        sender="reports@example.org", recipients=["a@example.org"], subject="s", text="t"
    )

    asyncio.run(
        smtp_sender.send_message(
            _configured(security="ssl", smtp_port=465, verify_tls=False),
            message,
            username="u",
            password="p",
        )
    )

    assert seen["hostname"] == "smtp.example.org" and seen["port"] == 465
    assert seen["use_tls"] is True and seen["start_tls"] is False
    assert seen["validate_certs"] is False
    assert (seen["username"], seen["password"]) == ("u", "p")
    assert seen["recipients"] == ["a@example.org"] and seen["sender"] == "reports@example.org"


def test_send_failure_hides_server_text(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(message, **kwargs):
        raise aiosmtplib.SMTPAuthenticationError(535, "bad password hunter2")

    monkeypatch.setattr(aiosmtplib, "send", fail)
    message = smtp_sender.build_message(
        sender="reports@example.org", recipients=["a@example.org"], subject="s", text="t"
    )

    with pytest.raises(MailSendError) as caught:
        asyncio.run(smtp_sender.send_message(_configured(), message, username=None, password=None))

    assert "SMTPAuthenticationError" in str(caught.value) and "535" in str(caught.value)
    assert "hunter2" not in str(caught.value)


def test_unconfigured_mail_is_refused_before_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_a, **_k):
        raise AssertionError("must not connect")

    monkeypatch.setattr(aiosmtplib, "send", boom)
    message = smtp_sender.build_message(
        sender="x@y.z", recipients=["a@example.org"], subject="s", text="t"
    )

    with pytest.raises(MailNotConfiguredError):
        asyncio.run(smtp_sender.send_message(MailSettings(), message, username=None, password=None))
    with pytest.raises(MailNotConfiguredError):
        asyncio.run(smtp_sender.check_connection(MailSettings(), username=None, password=None))


def test_check_connection_logs_in_and_reports_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeSMTP:
        def __init__(self, **kwargs):
            calls.append(f"init:{kwargs['hostname']}")

        async def __aenter__(self):
            calls.append("connect")
            return self

        async def __aexit__(self, *exc):
            calls.append("quit")

        async def login(self, user, password):
            calls.append(f"login:{user}")

        async def noop(self):
            calls.append("noop")

    monkeypatch.setattr(aiosmtplib, "SMTP", FakeSMTP)

    asyncio.run(smtp_sender.check_connection(_configured(), username="u", password="p"))

    assert calls == ["init:smtp.example.org", "connect", "login:u", "noop", "quit"]

    class Refusing(FakeSMTP):
        async def __aenter__(self):
            raise ConnectionRefusedError("secret detail")

    monkeypatch.setattr(aiosmtplib, "SMTP", Refusing)
    with pytest.raises(MailSendError) as caught:
        asyncio.run(smtp_sender.check_connection(_configured(), username=None, password=None))
    assert "ConnectionRefusedError" in str(caught.value) and "secret detail" not in str(
        caught.value
    )


# -- mail service: credential resolution ------------------------------------------------------


def test_mail_service_uses_only_global_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from services.credentials.secrets import CredentialLookupError
    from services.mail import mail_service
    from services.mail.errors import MailCredentialError

    seen: dict = {}

    class FakeManager:
        def __init__(self, db, acting_user_id=None):
            seen["acting_user_id"] = acting_user_id

        def generic_only(self, name):
            if name == "missing":
                raise CredentialLookupError("Credential 'missing' not found")
            seen["name"] = name
            return SimpleNamespace(username="u", password="p")

    monkeypatch.setattr(mail_service, "CredentialManager", FakeManager)
    service = mail_service.MailService(db=object())

    assert service._credentials(_configured(credential_name="smtp-user")) == ("u", "p")
    assert seen == {"acting_user_id": None, "name": "smtp-user"}
    assert service._credentials(_configured()) == (None, None)
    with pytest.raises(MailCredentialError):
        service._credentials(_configured(credential_name="missing"))


# -- allowed recipient domains ----------------------------------------------------------------


def test_allowed_domains_are_normalised_and_validated() -> None:
    settings = MailSettings(
        allowed_recipient_domains=[" Example.ORG ", "corp.example.org", "example.org"]
    )

    assert settings.allowed_recipient_domains == ["example.org", "corp.example.org"]
    assert MailSettings().allowed_recipient_domains == []
    for bad in (["a@example.org"], ["exa mple.org"], ["-x.org"], [""], ["x" * 300 + ".org"]):
        with pytest.raises(ValidationError):
            MailSettings(allowed_recipient_domains=bad)


def test_recipient_domain_check() -> None:
    from services.mail.recipients import disallowed_recipients

    allowed = ["example.org"]
    recipients = ["a@example.org", "b@Corp.Example.org", "c@evil.org", "d@notexample.org"]

    assert disallowed_recipients(recipients, allowed) == ["c@evil.org", "d@notexample.org"]
    assert disallowed_recipients(recipients, []) == []  # empty list: any domain
