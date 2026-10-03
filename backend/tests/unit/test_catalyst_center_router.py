"""Catalyst Center test-connection endpoint and permission wiring.

The generic CRUD behaviour (list/get/create/update/delete + status mapping) is covered by the
``catalyst_center`` variant in test_sources_crud_routers.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_catalyst_center_source_config_service
from routers.sources.catalyst_center import crud
from services.auth.rbac_seed import DEFAULT_PERMISSIONS
from services.auth.rbac_service import RBACService
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterValidationError,
)
from services.catalyst_center.common.version import parse_release
from services.catalyst_center.credentials import CatalystCenterCredentials

CREDS = CatalystCenterCredentials("https://10.10.20.85", "admin", "pw")
URL = "/api/sources/catalyst_center/test-connection"


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(crud.router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: {"sub": "t", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    config = MagicMock()
    config.resolve_credentials.return_value = CREDS
    config.resolve_inline_credentials.return_value = CREDS
    app.dependency_overrides[get_catalyst_center_source_config_service] = lambda: config

    device_service = MagicMock()
    device_service.test_connection = AsyncMock(return_value=parse_release("2.3.7.9-70050"))
    monkeypatch.setattr(
        crud.service_factory, "build_catalyst_center_device_service", lambda creds: device_service
    )
    with TestClient(app) as client:
        yield client, config, device_service


def test_saved_source_success_returns_release(harness):
    client, config, _ = harness
    r = client.post(URL, json={"source_id": "lab"})
    assert r.status_code == 200
    assert r.json() == {
        "success": True,
        "message": "Connection successful",
        "release": "2.3.7.9-70050",
    }
    config.resolve_credentials.assert_called_once_with("lab")


def test_inline_values_use_inline_resolver(harness):
    client, config, _ = harness
    r = client.post(URL, json={"url": "https://10.10.20.85", "credential_id": 5})
    assert r.status_code == 200
    assert config.resolve_inline_credentials.call_args.kwargs["credential_id"] == 5


def test_requires_source_or_inline(harness):
    client, _, _ = harness
    assert client.post(URL, json={}).status_code == 422
    both = {"source_id": "lab", "url": "https://x", "credential_id": 1}
    assert client.post(URL, json=both).status_code == 422


@pytest.mark.parametrize("exc", [CatalystCenterAuthError("bad"), CatalystCenterAPIError("down")])
def test_controller_failures_return_success_false_without_detail(harness, exc):
    client, _, device_service = harness
    device_service.test_connection.side_effect = exc
    body = client.post(URL, json={"source_id": "lab"}).json()
    assert body["success"] is False
    assert "ref:" in body["message"]
    assert str(exc) not in body["message"]


def test_validation_error_is_400(harness):
    client, _, device_service = harness
    device_service.test_connection.side_effect = CatalystCenterValidationError("bad url")
    assert client.post(URL, json={"source_id": "lab"}).status_code == 400


def test_unexpected_error_is_sanitised_500(harness):
    client, _, device_service = harness
    device_service.test_connection.side_effect = RuntimeError("secret internals")
    r = client.post(URL, json={"source_id": "lab"})
    assert r.status_code == 500
    assert "secret internals" not in r.text


def test_unknown_source_is_404(harness):
    from services.catalyst_center.source_config_service import CatalystCenterSourceNotFoundError

    client, config, _ = harness
    config.resolve_credentials.side_effect = CatalystCenterSourceNotFoundError("nope")
    assert client.post(URL, json={"source_id": "nope"}).status_code == 404


def test_permissions_are_seeded():
    seeded = {(r, a) for r, a, _ in DEFAULT_PERMISSIONS if r == "sources.catalyst_center"}
    assert seeded == {
        ("sources.catalyst_center", "read"),
        ("sources.catalyst_center", "write"),
        ("sources.catalyst_center", "delete"),
    }
