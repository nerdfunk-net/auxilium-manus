"""ACI device preview endpoint: filters, limit, errors, permissions, rate limit."""

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
from models.aci import AciDevice, AciDevicePreviewRequest
from routers.sources.aci import ops
from services.aci.common.exceptions import AciAPIError, AciAuthError, AciValidationError
from services.aci.credentials import AciCredentials
from services.aci.source_config_service import AciSourceNotFoundError
from services.auth.rbac_service import RBACService

CREDS = AciCredentials("https://10.10.20.14", "admin", "pw")
URL = "/api/sources/aci/lab/devices/preview"


def _device(node_id: int, **overrides) -> AciDevice:
    data = {
        "node_id": node_id,
        "name": f"leaf-{node_id}",
        "role": "leaf",
        "pod_id": 1,
        "model": "N9K-C9396PX",
        "serial_number": f"TEP-1-{node_id}",
        "software_version": "simsw-6.1(4h)",
        "fabric_state": "active",
        "tep_address": "10.0.64.64",
        "raw": {"fabric_node": {"secret-looking": "raw-only"}, "top_system": {}},
    }
    data.update(overrides)
    return AciDevice(**data)


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(ops.router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    config = MagicMock()
    config.resolve_credentials.return_value = CREDS
    app.dependency_overrides[get_aci_source_config_service] = lambda: config

    service = MagicMock()
    service.preview_devices = AsyncMock(return_value=((_device(101), _device(102)), False))
    monkeypatch.setattr(ops.service_factory, "build_aci_device_service", lambda creds: service)
    with TestClient(app) as client:
        yield client, config, service


def test_returns_a_summary_without_the_raw_record(harness):
    client, config, _ = harness
    r = client.post(URL, json={"filters": {"roles": ["leaf"]}, "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["truncated"] is False
    assert [d["node_id"] for d in body["devices"]] == [101, 102]
    first = body["devices"][0]
    assert first["name"] == "leaf-101"
    assert first["model"] == "N9K-C9396PX"
    assert first["fabric_state"] == "active"
    assert first["management_ip"] is None
    assert "raw" not in first and "raw-only" not in r.text and "tep_address" not in first
    config.resolve_credentials.assert_called_once_with("lab")


def test_filters_and_limit_reach_the_service(harness):
    client, _, service = harness
    client.post(URL, json={"filters": {"names": ["dc1-*"], "pod_ids": [2]}, "limit": 7})
    args = service.preview_devices.await_args
    assert args.args[0].names == ("dc1-*",)
    assert args.args[0].pod_ids == (2,)
    assert args.kwargs["limit"] == 7


def test_truncated_flag_is_passed_through(harness):
    client, _, service = harness
    service.preview_devices.return_value = ((_device(101),), True)
    assert client.post(URL, json={"limit": 1}).json()["truncated"] is True


def test_defaults_apply_with_an_empty_body(harness):
    client, _, service = harness
    assert client.post(URL, json={}).status_code == 200
    assert service.preview_devices.await_args.kwargs["limit"] == 25


@pytest.mark.parametrize("body", [{"limit": 0}, {"limit": 101}, {"unknown": 1}, {"filters": 5}])
def test_bad_request_bodies_are_422(harness, body):
    client, _, _ = harness
    assert client.post(URL, json=body).status_code == 422


def test_invalid_filters_are_400_before_any_apic_call(harness):
    client, config, service = harness
    r = client.post(URL, json={"filters": {"roles": ["controller"]}})
    assert r.status_code == 400
    assert "leaf or spine" in r.text
    config.resolve_credentials.assert_not_called()
    service.preview_devices.assert_not_called()


def test_unknown_source_is_404(harness):
    client, config, _ = harness
    config.resolve_credentials.side_effect = AciSourceNotFoundError("lab")
    assert client.post(URL, json={}).status_code == 404


@pytest.mark.parametrize("source_id", ["Bad%20Id%21", "1abc", "-lead", "a%20b", "a" * 65])
def test_a_malformed_source_id_is_400_not_500(harness, source_id):
    client, config, service = harness
    config.resolve_credentials.side_effect = ValueError("Invalid source_id: secret internals")
    r = client.post(f"/api/sources/aci/{source_id}/devices/preview", json={})
    assert r.status_code == 400
    assert "secret internals" not in r.text
    config.resolve_credentials.assert_not_called()
    service.preview_devices.assert_not_called()


def test_a_source_id_that_only_needs_normalising_is_passed_on(harness):
    client, config, _ = harness
    assert client.post("/api/sources/aci/Lab-1/devices/preview", json={}).status_code == 200
    config.resolve_credentials.assert_called_once_with("Lab-1")


def test_unusable_credential_is_400(harness):
    client, config, _ = harness
    config.resolve_credentials.side_effect = AciValidationError("no linked credential")
    assert client.post(URL, json={}).status_code == 400


@pytest.mark.parametrize("exc", [AciAuthError("bad"), AciAPIError("down")])
def test_apic_failures_are_502_without_detail(harness, exc):
    client, _, service = harness
    service.preview_devices.side_effect = exc
    r = client.post(URL, json={})
    assert r.status_code == 502
    assert str(exc) not in r.text


def test_validation_error_from_the_service_is_400(harness):
    client, _, service = harness
    service.preview_devices.side_effect = AciValidationError(
        "limit must be a positive whole number"
    )
    assert client.post(URL, json={}).status_code == 400


def test_unexpected_error_is_sanitised_500(harness):
    client, _, service = harness
    service.preview_devices.side_effect = RuntimeError("secret internals")
    r = client.post(URL, json={})
    assert r.status_code == 500
    assert "secret internals" not in r.text


def test_preview_needs_read_permission(monkeypatch):
    seen: list[tuple[str, str]] = []

    def has_permission(self, user_id, resource, action):
        seen.append((resource, action))
        return False

    monkeypatch.setattr(RBACService, "has_permission", has_permission)
    app = FastAPI()
    app.include_router(ops.router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    with TestClient(app) as client:
        assert client.post(URL, json={}).status_code == 403
    assert ("sources.aci", "read") in seen


def test_preview_request_forbids_unknown_fields():
    AciDevicePreviewRequest()
    with pytest.raises(ValidationError):
        AciDevicePreviewRequest(password="x")  # type: ignore[call-arg]
