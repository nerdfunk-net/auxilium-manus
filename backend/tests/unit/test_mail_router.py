"""/mail/settings: permissions, validation, credential check, connection test."""

from __future__ import annotations

import pytest
from _auth_helpers import make_auth_db, make_user, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from models.mail import MailSettings
from routers import mail as mail_router_module
from services.auth.rbac_service import RBACService
from services.mail.errors import MailCredentialError, MailSendError


class FakeSettingsService:
    stored = MailSettings()

    def __init__(self, db) -> None:
        pass

    def get(self):
        from services.mail.mail_settings_service import to_response

        return to_response(FakeSettingsService.stored)

    def update(self, settings):
        FakeSettingsService.stored = settings
        return self.get()


class FakeMailService:
    credential_error: Exception | None = None
    connect_error: Exception | None = None

    def __init__(self, db) -> None:
        pass

    def check_credential(self, settings) -> None:
        if FakeMailService.credential_error:
            raise FakeMailService.credential_error

    def check_connection(self) -> None:
        if FakeMailService.connect_error:
            raise FakeMailService.connect_error


@pytest.fixture
def granted(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    perms = {"system.mail:read", "system.mail:write"}
    monkeypatch.setattr(
        RBACService,
        "has_permission",
        lambda self, uid, resource, action: f"{resource}:{action}" in perms,
    )
    return perms


@pytest.fixture
def client(granted: set[str], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    FakeSettingsService.stored = MailSettings()
    FakeMailService.credential_error = None
    FakeMailService.connect_error = None
    monkeypatch.setattr(mail_router_module, "MailSettingsService", FakeSettingsService)
    monkeypatch.setattr(mail_router_module, "MailService", FakeMailService)
    app = FastAPI()
    app.include_router(mail_router_module.router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: make_user(1)
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    return TestClient(app)


VALID = {
    "smtp_server": "smtp.example.org",
    "smtp_port": 587,
    "security": "starttls",
    "verify_tls": True,
    "from_address": "reports@example.org",
    "credential_name": "smtp-user",
}


def test_get_and_update_round_trip(client: TestClient) -> None:
    assert client.get("/api/mail/settings").json()["configured"] is False

    saved = client.put("/api/mail/settings", json=VALID)

    assert saved.status_code == 200 and saved.json()["configured"] is True
    assert client.get("/api/mail/settings").json()["smtp_server"] == "smtp.example.org"


def test_validation_errors_are_422(client: TestClient) -> None:
    for bad in (
        {**VALID, "security": "none"},  # credential over a cleartext link
        {**VALID, "smtp_port": 0},
        {**VALID, "from_address": "nope"},
        {**VALID, "extra": 1},
    ):
        assert client.put("/api/mail/settings", json=bad).status_code == 422


def test_an_unusable_credential_is_rejected_on_save(client: TestClient) -> None:
    FakeMailService.credential_error = MailCredentialError("Credential 'smtp-user' not found")

    response = client.put("/api/mail/settings", json=VALID)

    assert response.status_code == 422 and "not found" in response.text
    assert FakeSettingsService.stored.smtp_server == ""  # nothing was saved


def test_connection_test_reports_success_and_failure(client: TestClient) -> None:
    ok = client.post("/api/mail/settings/test")
    FakeMailService.connect_error = MailSendError("could not send mail via s:587: SMTPConnectError")
    failed = client.post("/api/mail/settings/test")

    assert ok.json()["ok"] is True
    assert failed.status_code == 200 and failed.json()["ok"] is False
    assert "SMTPConnectError" in failed.json()["message"]


def test_permissions(client: TestClient, granted: set[str]) -> None:
    granted.discard("system.mail:write")
    assert client.get("/api/mail/settings").status_code == 200
    assert client.put("/api/mail/settings", json=VALID).status_code == 403
    assert client.post("/api/mail/settings/test").status_code == 403
    granted.discard("system.mail:read")
    assert client.get("/api/mail/settings").status_code == 403
