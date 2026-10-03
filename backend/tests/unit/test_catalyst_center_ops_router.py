"""Catalyst Center device preview endpoint (POST /sources/catalyst_center/{id}/devices/preview)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_catalyst_center_source_config_service
from models.catalyst_center import CatalystCenterDevice
from routers.sources.catalyst_center import ops
from services.auth.rbac_service import RBACService
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.source_config_service import CatalystCenterSourceNotFoundError
from services.credentials.source_credentials import SourceCredentialError

CREDS = CatalystCenterCredentials("https://10.10.20.85", "admin", "pw")
URL = "/api/sources/catalyst_center/lab-cc/devices/preview"


def _device(i: int) -> CatalystCenterDevice:
    return CatalystCenterDevice(
        id=f"uuid-{i}",
        hostname=f"sw{i}",
        management_ip=f"10.10.20.{170 + i}",
        family="Switches and Hubs",
        role="ACCESS",
        software_type="IOS-XE",
        software_version="17.12.1",
        platform_id="C9KV",
        reachability_status="Reachable",
        raw={"id": f"uuid-{i}", "snmpContact": "do-not-leak"},
    )


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(ops.router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: {"sub": "t", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    config = MagicMock()
    config.resolve_credentials.return_value = CREDS
    app.dependency_overrides[get_catalyst_center_source_config_service] = lambda: config

    device_service = MagicMock()
    device_service.preview_devices = AsyncMock(return_value=((_device(1), _device(2)), False))
    monkeypatch.setattr(
        ops.service_factory, "build_catalyst_center_device_service", lambda creds: device_service
    )
    with TestClient(app) as client:
        yield client, config, device_service, monkeypatch


def test_returns_device_summaries_without_the_raw_record(harness):
    client, config, device_service, _ = harness
    r = client.post(URL, json={"filters": {"roles": ["ACCESS"]}, "limit": 10})

    assert r.status_code == 200
    body = r.json()
    assert body["truncated"] is False
    assert [d["id"] for d in body["devices"]] == ["uuid-1", "uuid-2"]
    assert body["devices"][0] == {
        "id": "uuid-1",
        "hostname": "sw1",
        "management_ip": "10.10.20.171",
        "family": "Switches and Hubs",
        "role": "ACCESS",
        "software_type": "IOS-XE",
        "software_version": "17.12.1",
        "platform_id": "C9KV",
        "reachability_status": "Reachable",
    }
    assert "do-not-leak" not in r.text
    config.resolve_credentials.assert_called_once_with("lab-cc")


def test_filters_and_limit_reach_the_service(harness):
    client, _, device_service, _ = harness
    client.post(URL, json={"filters": {"hostnames": ["sw.*"], "cidr": "10.10.20.0/24"}, "limit": 7})
    filters = device_service.preview_devices.await_args.args[0]
    assert filters.hostnames == ("sw.*",)
    assert filters.cidr == "10.10.20.0/24"
    assert device_service.preview_devices.await_args.kwargs["limit"] == 7


def test_default_limit_and_empty_filters(harness):
    client, _, device_service, _ = harness
    assert client.post(URL, json={}).status_code == 200
    assert device_service.preview_devices.await_args.kwargs["limit"] == 25
    assert device_service.preview_devices.await_args.args[0].is_empty


def test_truncated_flag_is_passed_through(harness):
    client, _, device_service, _ = harness
    device_service.preview_devices.return_value = ((_device(1),), True)
    assert client.post(URL, json={"limit": 1}).json()["truncated"] is True


@pytest.mark.parametrize("limit", [0, -1, 101, "x"])
def test_limit_is_bounded(harness, limit):
    client, *_ = harness
    assert client.post(URL, json={"limit": limit}).status_code == 422


def test_invalid_filters_are_400(harness):
    client, _, device_service, _ = harness
    r = client.post(URL, json={"filters": {"hostname": ["x"]}})
    assert r.status_code == 400
    assert "Unknown filter" in r.json()["detail"]
    device_service.preview_devices.assert_not_awaited()


def test_filters_must_be_an_object(harness):
    client, *_ = harness
    assert client.post(URL, json={"filters": ["sw1"]}).status_code == 422


def test_unknown_source_is_404(harness):
    client, config, _, _ = harness
    config.resolve_credentials.side_effect = CatalystCenterSourceNotFoundError("lab-cc")
    assert client.post(URL, json={}).status_code == 404


@pytest.mark.parametrize(
    "exc", [CatalystCenterValidationError("no username"), SourceCredentialError("private")]
)
def test_credential_problems_are_400(harness, exc):
    client, config, _, _ = harness
    config.resolve_credentials.side_effect = exc
    assert client.post(URL, json={}).status_code == 400


def test_service_validation_error_is_400(harness):
    client, _, device_service, _ = harness
    device_service.preview_devices.side_effect = CatalystCenterValidationError("bad request")
    r = client.post(URL, json={})
    assert r.status_code == 400
    assert r.json()["detail"] == "bad request"


@pytest.mark.parametrize(
    "exc", [CatalystCenterAPIError("controller down"), CatalystCenterAuthError("denied")]
)
def test_upstream_failures_are_sanitised_502(harness, exc):
    client, _, device_service, _ = harness
    device_service.preview_devices.side_effect = exc
    r = client.post(URL, json={})
    assert r.status_code == 502
    assert set(r.json()["detail"]) == {"message", "error_id"}
    assert str(exc) not in r.text


def test_unexpected_error_is_sanitised_500(harness):
    client, _, device_service, _ = harness
    device_service.preview_devices.side_effect = RuntimeError("secret internals")
    r = client.post(URL, json={})
    assert r.status_code == 500
    assert "secret internals" not in r.text


def test_requires_read_permission(harness):
    client, _, _, monkeypatch = harness
    seen = []

    def deny(self, user_id, resource, action):
        seen.append((resource, action))
        return False

    monkeypatch.setattr(RBACService, "has_permission", deny)
    assert client.post(URL, json={}).status_code == 403
    assert ("sources.catalyst_center", "read") in seen
