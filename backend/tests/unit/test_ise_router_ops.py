"""Behavioural tests for routers/sources/ise/ops.py (device + NDG endpoints)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_ise_source_config_service
from routers.sources.ise import ops
from services.auth.rbac_service import RBACService
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError
from services.ise.credentials import ISECredentials
from services.ise.redaction import REDACTED

CREDS = ISECredentials("https://10.10.20.77", "admin", "pw")
BASE = "/api/sources/ise/lab"

RAW_DEVICE = {
    "NetworkDevice": {
        "id": "d1",
        "name": "sw1",
        "tacacsSettings": {"sharedSecret": "tacacs-key", "connectModeOptions": "OFF"},
        "authenticationSettings": {"radiusSharedSecret": "radius-key"},
    }
}


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
    app.dependency_overrides[get_ise_source_config_service] = lambda: config

    devices = MagicMock()
    for name in (
        "list_devices",
        "list_devices_by_group",
        "get_device",
        "get_device_by_name",
        "create_device",
        "update_device",
        "delete_device",
    ):
        setattr(devices, name, AsyncMock())
    groups = MagicMock()
    for name in (
        "list_groups",
        "list_all_groups",
        "create_root_group",
        "create_child_group",
        "create_location",
        "get_group_by_name",
        "get_group",
        "update_group",
        "delete_group",
    ):
        setattr(groups, name, AsyncMock())
    monkeypatch.setattr(ops.service_factory, "build_ise_network_device_service", lambda c: devices)
    monkeypatch.setattr(
        ops.service_factory, "build_ise_network_device_group_service", lambda c: groups
    )
    with TestClient(app) as client:
        yield client, devices, groups


def test_get_device_never_returns_shared_secrets(harness) -> None:
    client, devices, _ = harness
    devices.get_device.return_value = RAW_DEVICE

    body = client.get(f"{BASE}/devices/d1").json()["NetworkDevice"]

    assert body["tacacsSettings"]["sharedSecret"] == REDACTED
    assert body["authenticationSettings"]["radiusSharedSecret"] == REDACTED
    assert body["name"] == "sw1"
    # the service itself still returns the raw payload (steps need it)
    assert RAW_DEVICE["NetworkDevice"]["tacacsSettings"]["sharedSecret"] == "tacacs-key"


def test_get_device_by_name_never_returns_shared_secrets(harness) -> None:
    client, devices, _ = harness
    devices.get_device_by_name.return_value = RAW_DEVICE

    body = client.get(f"{BASE}/devices/name/sw1").json()

    assert body["NetworkDevice"]["tacacsSettings"]["sharedSecret"] == REDACTED


def test_update_response_does_not_echo_old_or_new_secret(harness) -> None:
    client, devices, _ = harness
    devices.update_device.return_value = {
        "UpdatedFieldsList": {
            "updatedField": [
                {"field": "tacacsSettings.sharedSecret", "oldValue": "a", "newValue": "b"}
            ]
        }
    }

    body = client.put(f"{BASE}/devices/d1", json={"tacacsSettings": {"sharedSecret": "b"}}).json()

    entry = body["UpdatedFieldsList"]["updatedField"][0]
    assert entry["oldValue"] == REDACTED and entry["newValue"] == REDACTED


def test_create_device_forwards_payload_and_returns_location(harness) -> None:
    client, devices, _ = harness
    devices.create_device.return_value = {"id": "g1", "location": "https://ise/x/g1"}

    r = client.post(f"{BASE}/devices", json={"name": "sw1", "NetworkDeviceIPList": []})

    assert r.status_code == 201
    assert r.json() == {"id": "g1", "location": "https://ise/x/g1"}
    assert devices.create_device.await_args.args[0]["name"] == "sw1"


@pytest.mark.parametrize(
    ("method", "path", "service", "call", "payload"),
    [
        ("get", "/devices/d1", "devices", "get_device", None),
        ("get", "/devices/name/sw1", "devices", "get_device_by_name", None),
        ("put", "/devices/d1", "devices", "update_device", {"description": "x"}),
        ("delete", "/devices/d1", "devices", "delete_device", None),
        ("put", "/network-device-groups/g1", "groups", "update_group", {"description": "x"}),
        ("delete", "/network-device-groups/g1", "groups", "delete_group", None),
    ],
)
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ISENotFoundError("nope"), 404),
        (ISEValidationError("bad"), 400),
        (ISEAPIError("down"), 502),
    ],
)
def test_error_mapping(harness, method, path, service, call, payload, error, status) -> None:
    client, devices, groups = harness
    getattr(devices if service == "devices" else groups, call).side_effect = error

    r = getattr(client, method)(f"{BASE}{path}", **({"json": payload} if payload else {}))

    assert r.status_code == status


def test_create_group_validation_error_is_400(harness) -> None:
    client, _, groups = harness
    groups.create_root_group.side_effect = ISEValidationError("exists")

    r = client.post(f"{BASE}/network-device-groups/roots", json={"name": "foo"})

    assert r.status_code == 400


def test_list_all_groups_maps_truncation_flag(harness) -> None:
    client, _, groups = harness
    groups.list_all_groups.return_value = ([{"id": "g", "name": "A#A", "description": None}], True)

    body = client.get(f"{BASE}/network-device-groups/all").json()

    assert body["truncated"] is True and body["total"] == 1


_ALL_ENDPOINTS = [
    ("get", "/devices", "devices", "list_devices", None),
    ("get", "/devices/ndg/grp", "devices", "list_devices_by_group", None),
    ("get", "/devices/d1", "devices", "get_device", None),
    ("get", "/devices/name/sw1", "devices", "get_device_by_name", None),
    ("post", "/devices", "devices", "create_device", {"name": "sw1"}),
    ("put", "/devices/d1", "devices", "update_device", {"description": "x"}),
    ("delete", "/devices/d1", "devices", "delete_device", None),
    (
        "post",
        "/location-groups",
        "groups",
        "create_location",
        {"name": "n", "parent_group": "All Locations"},
    ),
    ("get", "/network-device-groups/", "groups", "list_groups", None),
    ("get", "/network-device-groups/all", "groups", "list_all_groups", None),
    ("post", "/network-device-groups/roots", "groups", "create_root_group", {"name": "n"}),
    (
        "post",
        "/network-device-groups/children",
        "groups",
        "create_child_group",
        {"name": "n", "parent_group": "p#p"},
    ),
    ("get", "/network-device-groups/name/n", "groups", "get_group_by_name", None),
    ("put", "/network-device-groups/g1", "groups", "update_group", {"description": "x"}),
    ("delete", "/network-device-groups/g1", "groups", "delete_group", None),
]


@pytest.mark.parametrize(("method", "path", "service", "call", "payload"), _ALL_ENDPOINTS)
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ISEValidationError("bad"), 400),
        (ISEAPIError("down"), 502),
        (RuntimeError("boom-secret"), 500),
    ],
)
def test_every_endpoint_maps_errors_without_leaking_text(
    harness, method, path, service, call, payload, error, status
) -> None:
    client, devices, groups = harness
    getattr(devices if service == "devices" else groups, call).side_effect = error

    r = getattr(client, method)(f"{BASE}{path}", **({"json": payload} if payload else {}))

    assert r.status_code == status
    if status >= 500:
        assert "boom-secret" not in r.text


def test_list_devices_maps_search_result(harness) -> None:
    client, devices, _ = harness
    devices.list_devices.return_value = {
        "SearchResult": {
            "total": 1,
            "resources": [{"id": "d1", "name": "sw1"}],
            "nextPage": {"href": "https://ise/next"},
        }
    }

    body = client.get(f"{BASE}/devices").json()

    assert body["total"] == 1 and body["next_page"] == "https://ise/next"


def test_list_devices_by_group_maps_search_result(harness) -> None:
    client, devices, _ = harness
    devices.list_devices_by_group.return_value = {"SearchResult": {"total": 0, "resources": []}}

    body = client.get(f"{BASE}/devices/ndg/grp").json()

    assert body["total"] == 0 and body["next_page"] is None


def test_group_by_name_missing_is_404(harness) -> None:
    client, _, groups = harness
    groups.get_group_by_name.return_value = None

    assert client.get(f"{BASE}/network-device-groups/name/n").status_code == 404


def test_delete_device_returns_204(harness) -> None:
    client, devices, _ = harness

    r = client.delete(f"{BASE}/devices/d1")

    assert r.status_code == 204
    devices.delete_device.assert_awaited_once_with("d1")


def test_unknown_source_is_404(harness) -> None:
    from services.ise.source_config_service import ISESourceNotFoundError

    client, _, _ = harness
    client.app.dependency_overrides[
        get_ise_source_config_service
    ]().resolve_credentials.side_effect = ISESourceNotFoundError("lab")

    assert client.get(f"{BASE}/devices").status_code == 404
