"""/reports/definitions and /reports/snapshots: permissions, validation, error mapping, flow."""

from __future__ import annotations

from typing import Any

import pytest
from _auth_helpers import make_auth_db, make_user, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.base import Base
from core.models.report_data_records import ReportDataRecord
from core.models.report_datasets import ReportDataset
from core.models.report_definitions import ReportDefinition
from core.models.report_snapshots import ReportSnapshot
from core.models.templates import Template
from routers.report_definitions import get_report_mailer, get_report_service, router
from services.auth.rbac_service import RBACService
from services.reports.report_mailer import ReportMailer
from services.reports.report_service import ReportService

SECTION: dict[str, Any] = {
    "id": "per-location",
    "title": "Devices per location",
    "query": {
        "dataset": "inventory",
        "group_by": ["location"],
        "metrics": [{"op": "count", "alias": "devices"}],
    },
}


@pytest.fixture
def granted(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """Permissions the fake user holds, as ``"resource:action"``."""
    perms = {"reports:read", "reports:write", "reports:delete", "reports:send"}

    def has_permission(self, user_id, resource, action) -> bool:
        return f"{resource}:{action}" in perms

    monkeypatch.setattr(RBACService, "has_permission", has_permission)
    return perms


@pytest.fixture(autouse=True)
def _default_mail_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from models.mail import MailSettings

    monkeypatch.setattr(
        "services.reports.report_mailer.MailService.settings", lambda self: MailSettings()
    )


@pytest.fixture
def client(granted: set[str]) -> TestClient:
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
    session.add(
        Template(
            name="exec-summary",
            category="report",
            template_type="jinja2",
            content="{{ report.name }}: {{ sections['per-location'].value }} devices",
        )
    )
    session.add(Template(name="device-cfg", category="netmiko", template_type="jinja2", content=""))
    session.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: make_user(1, username="alice")
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    app.dependency_overrides[get_report_service] = lambda: ReportService(session)
    app.dependency_overrides[get_report_mailer] = lambda: ReportMailer(session)
    return TestClient(app)


def _create(client: TestClient, name: str = "Fleet") -> dict[str, Any]:
    response = client.post("/api/reports/definitions", json={"name": name, "sections": [SECTION]})
    assert response.status_code == 201, response.text
    return response.json()


def test_full_flow(client: TestClient) -> None:
    created = _create(client)
    assert created["sections"][0]["presentation"] == "table"

    listed = client.get("/api/reports/definitions").json()
    assert [(d["name"], d["section_count"], d["snapshot_count"]) for d in listed] == [
        ("Fleet", 1, 0)
    ]

    updated = client.put(
        f"/api/reports/definitions/{created['id']}", json={"description": "all sites"}
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "all sites"

    generated = client.post(f"/api/reports/definitions/{created['id']}/generate")
    assert generated.status_code == 201, generated.text
    body = generated.json()
    assert body["status"] == "complete"
    assert body["generated_by"] == "alice"
    assert body["content"]["sections"][0]["result"]["rows"] == [["dc1", 1]]

    snaps = client.get("/api/reports/snapshots", params={"definition_id": created["id"]}).json()
    assert [s["id"] for s in snaps] == [body["id"]]
    assert "content" not in snaps[0]
    assert client.get(f"/api/reports/snapshots/{body['id']}").json()["content"]["name"] == "Fleet"

    assert client.delete(f"/api/reports/snapshots/{body['id']}").status_code == 204
    assert client.get(f"/api/reports/snapshots/{body['id']}").status_code == 404
    assert client.delete(f"/api/reports/definitions/{created['id']}").status_code == 204
    assert client.get(f"/api/reports/definitions/{created['id']}").status_code == 404


def test_permissions_are_enforced_per_action(client: TestClient, granted: set[str]) -> None:
    created = _create(client)
    snapshot = client.post(f"/api/reports/definitions/{created['id']}/generate").json()

    granted.discard("reports:write")
    assert client.post("/api/reports/definitions", json={"name": "x"}).status_code == 403
    assert (
        client.put(f"/api/reports/definitions/{created['id']}", json={"name": "y"}).status_code
        == 403
    )
    assert client.post(f"/api/reports/definitions/{created['id']}/generate").status_code == 403
    assert client.get("/api/reports/definitions").status_code == 200

    granted.discard("reports:delete")
    assert client.delete(f"/api/reports/definitions/{created['id']}").status_code == 403
    assert client.delete(f"/api/reports/snapshots/{snapshot['id']}").status_code == 403

    granted.discard("reports:read")
    assert client.get("/api/reports/definitions").status_code == 403
    assert client.get("/api/reports/snapshots").status_code == 403
    assert client.get(f"/api/reports/snapshots/{snapshot['id']}").status_code == 403


def test_duplicate_name_is_409(client: TestClient) -> None:
    _create(client)
    response = client.post("/api/reports/definitions", json={"name": "Fleet"})
    assert response.status_code == 409


def test_missing_ids_are_404(client: TestClient) -> None:
    assert client.get("/api/reports/definitions/9").status_code == 404
    assert client.put("/api/reports/definitions/9", json={"name": "x"}).status_code == 404
    assert client.delete("/api/reports/definitions/9").status_code == 404
    assert client.post("/api/reports/definitions/9/generate").status_code == 404
    assert client.get("/api/reports/snapshots/9").status_code == 404
    assert client.delete("/api/reports/snapshots/9").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "unknown": 1},
        {"name": "   "},
        {"name": "x", "sections": [SECTION, SECTION]},
        {"name": "x", "sections": [{**SECTION, "id": "Bad Id"}]},
        {"name": "x", "sections": [{**SECTION, "presentation": "pie"}]},
        {"name": "x", "sections": [{**SECTION, "extra": 1}]},
    ],
)
def test_invalid_bodies_are_422(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/api/reports/definitions", json=body).status_code == 422


def test_unknown_source_is_422(client: TestClient) -> None:
    section = {**SECTION, "query": {**SECTION["query"], "source": "nope"}}
    response = client.post("/api/reports/definitions", json={"name": "x", "sections": [section]})
    assert response.status_code == 422
    assert "nope" in response.text


def test_empty_update_is_422(client: TestClient) -> None:
    created = _create(client)
    assert client.put(f"/api/reports/definitions/{created['id']}", json={}).status_code == 422
    assert (
        client.put(f"/api/reports/definitions/{created['id']}", json={"name": None}).status_code
        == 422
    )


def test_failed_section_gives_partial_snapshot(client: TestClient) -> None:
    section = {**SECTION, "query": {**SECTION["query"], "dataset": "missing"}}
    created = client.post(
        "/api/reports/definitions", json={"name": "x", "sections": [section]}
    ).json()

    body = client.post(f"/api/reports/definitions/{created['id']}/generate").json()

    assert body["status"] == "partial"
    assert body["content"]["sections"][0]["status"] == "error"


def test_template_is_validated_and_used_for_the_snapshot_body(client: TestClient) -> None:
    created = client.post(
        "/api/reports/definitions", json={"name": "Fleet", "sections": [SECTION], "template_id": 1}
    )
    assert created.status_code == 201, created.text
    assert created.json()["template_id"] == 1

    body = client.post(f"/api/reports/definitions/{created.json()['id']}/generate").json()

    assert body["status"] == "complete"
    assert body["content"]["body"]["markdown"] == "Fleet: 1 devices"
    assert body["content"]["body"]["template_name"] == "exec-summary"


def test_a_non_report_template_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/reports/definitions", json={"name": "x", "sections": [SECTION], "template_id": 2}
    )

    assert response.status_code == 422
    assert "report template" in response.text


def test_the_template_can_be_removed_again(client: TestClient) -> None:
    created = client.post(
        "/api/reports/definitions", json={"name": "x", "sections": [SECTION], "template_id": 1}
    ).json()

    updated = client.put(f"/api/reports/definitions/{created['id']}", json={"template_id": None})

    assert updated.status_code == 200 and updated.json()["template_id"] is None


def test_template_preview_renders_against_a_snapshot(client: TestClient, granted: set[str]) -> None:
    created = _create(client)
    snapshot = client.post(f"/api/reports/definitions/{created['id']}/generate").json()
    url = f"/api/reports/snapshots/{snapshot['id']}/preview-template"

    ok = client.post(url, json={"content": "{{ sections['per-location'].value }} devices"})
    broken = client.post(url, json={"content": "{{ nope.x }}"})
    missing = client.post("/api/reports/snapshots/99/preview-template", json={"content": "x"})
    too_big = client.post(url, json={"content": "x" * 200_001})

    assert ok.status_code == 200 and ok.json() == {"markdown": "1 devices", "error": None}
    assert (
        broken.status_code == 200 and broken.json()["markdown"] is None and broken.json()["error"]
    )
    assert missing.status_code == 404
    assert too_big.status_code == 422
    granted.discard("reports:read")
    assert client.post(url, json={"content": "x"}).status_code == 403


def _snapshot(client: TestClient) -> int:
    created = _create(client)
    return client.post(f"/api/reports/definitions/{created['id']}/generate").json()["id"]


def test_pdf_download(client: TestClient, granted: set[str]) -> None:
    snapshot_id = _snapshot(client)

    response = client.get(f"/api/reports/snapshots/{snapshot_id}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith('attachment; filename="Fleet')
    assert response.content.startswith(b"%PDF-")
    assert client.get("/api/reports/snapshots/99/pdf").status_code == 404
    granted.discard("reports:read")
    assert client.get(f"/api/reports/snapshots/{snapshot_id}/pdf").status_code == 403


def test_send_needs_reports_send_and_maps_mail_errors(
    client: TestClient, granted: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.mail.errors import MailNotConfiguredError, MailSendError

    snapshot_id = _snapshot(client)
    url = f"/api/reports/snapshots/{snapshot_id}/send"
    body = {"to": ["a@example.org"], "message": "hi"}
    outcome: dict = {"error": None}

    def fake_send(self, **kwargs):
        if outcome["error"] is not None:
            raise outcome["error"]
        outcome["kwargs"] = kwargs

    monkeypatch.setattr("services.reports.report_mailer.MailService.send", fake_send)

    ok = client.post(url, json=body)
    assert ok.status_code == 200 and ok.json() == {
        "sent_to": ["a@example.org"],
        "pdf_attached": True,
    }
    assert outcome["kwargs"]["subject"].startswith("Fleet")

    outcome["error"] = MailNotConfiguredError("Mail is not configured")
    not_configured = client.post(url, json=body)
    assert not_configured.status_code == 409 and "not configured" in not_configured.text
    outcome["error"] = MailSendError("could not send mail via smtp.internal:25: SMTPConnectError")
    bad_gateway = client.post(url, json=body)
    assert bad_gateway.status_code == 502
    assert "smtp.internal" not in bad_gateway.text and "SMTPConnectError" not in bad_gateway.text
    assert client.post("/api/reports/snapshots/99/send", json=body).status_code == 404
    assert client.post(url, json={"to": ["nope"]}).status_code == 422
    assert client.post(url, json={"to": []}).status_code == 422

    granted.discard("reports:send")
    assert client.post(url, json=body).status_code == 403
    assert client.get(f"/api/reports/snapshots/{snapshot_id}/pdf").status_code == 200  # read only


def test_default_recipients_are_cleaned_saved_and_returned(client: TestClient) -> None:
    created = client.post(
        "/api/reports/definitions",
        json={
            "name": "Fleet",
            "sections": [SECTION],
            "default_recipients": ["Ops <ops@example.org>", "ops@example.org", "dev@example.org"],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["default_recipients"] == ["ops@example.org", "dev@example.org"]

    updated = client.put(
        f"/api/reports/definitions/{created.json()['id']}", json={"default_recipients": []}
    )
    assert updated.status_code == 200 and updated.json()["default_recipients"] == []
    assert (
        client.put(
            f"/api/reports/definitions/{created.json()['id']}", json={"default_recipients": ["x"]}
        ).status_code
        == 422
    )
    assert _create(client, "Other")["default_recipients"] == []


def test_credential_and_domain_problems_do_not_expose_internals(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.mail.errors import MailCredentialError

    url = f"/api/reports/snapshots/{_snapshot(client)}/send"
    body = {"to": ["a@example.org"]}
    state: dict = {}

    def fake_send(self, **kwargs):
        raise state["error"]

    monkeypatch.setattr("services.reports.report_mailer.MailService.send", fake_send)

    state["error"] = MailCredentialError("Credential 'corp-smtp-admin' not found in vault")
    credential = client.post(url, json=body)
    assert credential.status_code == 409 and "corp-smtp-admin" not in credential.text

    monkeypatch.setattr(
        "services.reports.report_mailer.MailService.settings",
        lambda self: __import__("models.mail", fromlist=["MailSettings"]).MailSettings(
            smtp_server="s", from_address="a@b.cd", allowed_recipient_domains=["corp.example"]
        ),
    )
    blocked = client.post(url, json=body)
    assert (
        blocked.status_code == 422
        and "a@example.org" in blocked.text
        and "corp.example" in blocked.text
    )


def test_pdf_layout_failures_are_422_not_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.reports.pdf_renderer import PdfRenderError

    snapshot_id = _snapshot(client)

    def fail(self, snapshot_id):
        raise PdfRenderError("The report could not be laid out as a PDF")

    monkeypatch.setattr("services.reports.report_mailer.ReportMailer.pdf", fail)

    response = client.get(f"/api/reports/snapshots/{snapshot_id}/pdf")

    assert response.status_code == 422 and "laid out" in response.text


def test_a_report_name_cannot_contain_a_line_break(client: TestClient) -> None:
    response = client.post("/api/reports/definitions", json={"name": "a\nb", "sections": []})

    assert response.status_code == 422
