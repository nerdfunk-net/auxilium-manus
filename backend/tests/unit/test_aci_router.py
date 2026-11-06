"""ACI test-connection endpoint, permission wiring and request-model strictness.

The generic CRUD behaviour (list/get/create/update/delete + status mapping) is covered by the
``aci`` variant in test_sources_crud_routers.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_aci_source_config_service
from models.aci import (
    AciSourceCreateRequest,
    AciSourceUpdateRequest,
    AciTestConnectionRequest,
)
from routers.sources.aci import crud
from services.aci.common.exceptions import AciAPIError, AciAuthError, AciValidationError
from services.aci.credentials import AciCredentials
from services.aci.source_config_service import AciSourceNotFoundError
from services.auth.rbac_seed import DEFAULT_PERMISSIONS
from services.auth.rbac_service import RBACService

CREDS = AciCredentials("https://10.10.20.14", "admin", "pw")
URL = "/api/sources/aci/test-connection"


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(crud.router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    config = MagicMock()
    config.resolve_credentials.return_value = CREDS
    config.resolve_inline_credentials.return_value = CREDS
    app.dependency_overrides[get_aci_source_config_service] = lambda: config

    device_service = MagicMock()
    device_service.test_connection = AsyncMock(return_value="6.1(4h)")
    monkeypatch.setattr(
        crud.service_factory, "build_aci_device_service", lambda creds: device_service
    )
    with TestClient(app) as client:
        yield client, config, device_service


def test_saved_source_success_returns_version(harness):
    client, config, _ = harness
    r = client.post(URL, json={"source_id": "lab"})
    assert r.status_code == 200
    assert r.json() == {"success": True, "message": "Connection successful", "version": "6.1(4h)"}
    config.resolve_credentials.assert_called_once_with("lab")


def test_missing_version_is_returned_as_null(harness):
    client, _, device_service = harness
    device_service.test_connection.return_value = None
    body = client.post(URL, json={"source_id": "lab"}).json()
    assert body["success"] is True
    assert body["version"] is None


def test_inline_values_use_inline_resolver(harness):
    client, config, _ = harness
    r = client.post(URL, json={"url": "https://10.10.20.14", "credential_id": 5})
    assert r.status_code == 200
    assert config.resolve_inline_credentials.call_args.kwargs["credential_id"] == 5


def test_requires_source_or_inline(harness):
    client, _, _ = harness
    assert client.post(URL, json={}).status_code == 422
    both = {"source_id": "lab", "url": "https://x", "credential_id": 1}
    assert client.post(URL, json=both).status_code == 422


def test_unknown_fields_are_rejected(harness):
    client, _, _ = harness
    assert client.post(URL, json={"source_id": "lab", "password": "x"}).status_code == 422


@pytest.mark.parametrize("exc", [AciAuthError("bad"), AciAPIError("down")])
def test_apic_failures_return_success_false_without_detail(harness, exc):
    client, _, device_service = harness
    device_service.test_connection.side_effect = exc
    body = client.post(URL, json={"source_id": "lab"}).json()
    assert body["success"] is False
    assert "ref:" in body["message"]
    assert str(exc) not in body["message"]


def test_validation_error_is_400(harness):
    client, _, device_service = harness
    device_service.test_connection.side_effect = AciValidationError("bad url")
    assert client.post(URL, json={"source_id": "lab"}).status_code == 400


def test_unexpected_error_is_sanitised_500(harness):
    client, _, device_service = harness
    device_service.test_connection.side_effect = RuntimeError("secret internals")
    r = client.post(URL, json={"source_id": "lab"})
    assert r.status_code == 500
    assert "secret internals" not in r.text


def test_unknown_source_is_404(harness):
    client, config, _ = harness
    config.resolve_credentials.side_effect = AciSourceNotFoundError("nope")
    assert client.post(URL, json={"source_id": "nope"}).status_code == 404


@pytest.mark.parametrize("source_id", ["Bad Id!", "1abc", "../x", "-lead", "a b"])
def test_a_malformed_source_id_is_400_not_500(harness, source_id):
    """The real config service raises ValueError for it; that must not reach FastAPI."""
    client, config, device_service = harness
    config.resolve_credentials.side_effect = ValueError("Invalid source_id: secret internals")
    r = client.post(URL, json={"source_id": source_id})
    assert r.status_code == 400
    assert "secret internals" not in r.text
    config.resolve_credentials.assert_not_called()
    device_service.test_connection.assert_not_called()


def test_a_source_id_that_only_needs_normalising_is_passed_on(harness):
    client, config, _ = harness
    assert client.post(URL, json={"source_id": " Lab-1 "}).status_code == 200
    config.resolve_credentials.assert_called_once_with(" Lab-1 ")


def test_unusable_inline_credential_is_400(harness):
    client, config, _ = harness
    config.resolve_inline_credentials.side_effect = AciValidationError("private credential")
    r = client.post(URL, json={"url": "https://x", "credential_id": 5})
    assert r.status_code == 400


def test_test_connection_needs_write_permission(monkeypatch):
    """A user who may only read ACI sources cannot probe an APIC with arbitrary credentials."""
    seen: list[tuple[str, str]] = []

    def has_permission(self, user_id, resource, action):
        seen.append((resource, action))
        return action == "read"

    monkeypatch.setattr(RBACService, "has_permission", has_permission)
    app = FastAPI()
    app.include_router(crud.router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    with TestClient(app) as client:
        assert client.post(URL, json={"source_id": "lab"}).status_code == 403
    assert ("sources.aci", "write") in seen


def test_permissions_are_seeded():
    seeded = {(r, a) for r, a, _ in DEFAULT_PERMISSIONS}
    assert {("sources.aci", "read"), ("sources.aci", "write"), ("sources.aci", "delete")} <= seeded


def test_request_models_forbid_unknown_fields():
    for model, payload in (
        (AciSourceCreateRequest, {"source_id": "lab", "url": "https://x", "credential_id": 1}),
        (AciSourceUpdateRequest, {}),
        (AciTestConnectionRequest, {"source_id": "lab"}),
    ):
        model(**payload)
        with pytest.raises(ValidationError):
            model(**payload, password="x")
