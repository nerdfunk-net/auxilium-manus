"""REST API for the collected client data: permission, filters, paging, history."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.rate_limit as rate_limit_module
from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from routers import client_data
from services.auth.rbac_seed import DEFAULT_PERMISSIONS, VIEWER_PERMISSIONS
from services.auth.rbac_service import RBACService

ROW = {
    "mac_address": "aabb.ccdd.0001",
    "device_name": "swB",
    "port": "Gi1/0/5",
    "vlan": "10",
    "vrf": None,
    "ip_address": "10.0.0.5",
    "hostname": "pc1.example.net",
    "macs_on_port": 1,
    "is_uplink": False,
    "likely_location": True,
    "session_id": "run-1",
    "collected_at": "2026-11-07T12:00:00+00:00",
    "ip_collected_at": "2026-11-07T11:00:00+00:00",
}


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get_client_data(self, **kwargs):
        self.calls.append(("data", kwargs))
        return [ROW], 1

    def get_client_history(self, **kwargs):
        self.calls.append(("history", kwargs))
        return {
            "ip_history": [],
            "mac_history": [
                {
                    "mac_address": "aabb.ccdd.0001",
                    "port": "Gi1/0/5",
                    "vlan": "10",
                    "device_name": "swB",
                    "ip_address": "10.0.0.5",
                    "collected_at": "2026-11-07T12:00:00+00:00",
                }
            ],
            "hostname_history": [],
        }

    def get_collections(self):
        self.calls.append(("collections", {}))
        return [
            {
                "device_name": "swB",
                "collected_at": "2026-11-07T12:00:00+00:00",
                "arp_collected_at": "2026-11-07T12:00:00+00:00",
                "mac_collected_at": "2026-11-07T11:00:00+00:00",
                "arp_status": "ok",
                "mac_status": "ok",
                "vrf_status": "not_supported",
                "vrf_count": 1,
                "vrfs": [{"name": "CUST", "status": "ok", "rows": 0}],
                "arp_rows": 3,
                "mac_rows": 20,
            }
        ]


@pytest.fixture
def harness(monkeypatch):
    allowed = {"value": True}
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: allowed["value"])
    monkeypatch.setattr(
        rate_limit_module.service_factory, "build_user_rate_limiter", lambda *a, **k: MagicMock()
    )
    app = FastAPI()
    app.include_router(client_data.router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    service = FakeService()
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    app.dependency_overrides[client_data.get_client_data_service] = lambda: service
    with TestClient(app) as client:
        yield client, service, allowed


def test_the_permission_is_seeded_but_not_part_of_the_viewer_role() -> None:
    assert ("client_data", "read") in {(r, a) for r, a, _ in DEFAULT_PERMISSIONS}
    assert ("client_data", "read") not in VIEWER_PERMISSIONS


def test_a_user_without_the_permission_gets_403_on_every_route(harness) -> None:
    client, service, allowed = harness
    allowed["value"] = False

    for url in (
        "/api/client-data",
        "/api/client-data/history?mac_address=aabb.ccdd.0001",
        "/api/client-data/devices",
    ):
        response = client.get(url)
        assert response.status_code == 403, url
        assert "client_data:read" in response.json()["detail"]
    assert service.calls == []


def test_list_returns_a_page_with_the_uplink_flags(harness) -> None:
    client, service, _ = harness

    response = client.get("/api/client-data?mac_address=aabb&hide_uplinks=true&page=2&page_size=10")

    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["page"], body["page_size"]) == (1, 2, 10)
    assert body["items"][0]["likely_location"] is True
    assert body["items"][0]["macs_on_port"] == 1
    assert body["items"][0]["ip_collected_at"] == "2026-11-07T11:00:00+00:00"
    _, kwargs = service.calls[0]
    assert kwargs["mac_address"] == "aabb"
    assert kwargs["hide_uplinks"] is True
    assert (kwargs["page"], kwargs["page_size"]) == (2, 10)
    assert kwargs["exact"] is False


def test_exact_is_passed_through(harness) -> None:
    client, service, _ = harness

    client.get("/api/client-data?ip_address=10.0.0.5&exact=true")

    assert service.calls[0][1]["exact"] is True


@pytest.mark.parametrize(
    "query", ["page=0", "page_size=0", "page_size=501", "device_name=" + "x" * 256]
)
def test_invalid_paging_and_filters_are_rejected(harness, query: str) -> None:
    client, service, _ = harness

    assert client.get(f"/api/client-data?{query}").status_code == 422
    assert service.calls == []


def test_unknown_query_parameters_do_not_change_the_query(harness) -> None:
    client, service, _ = harness

    assert client.get("/api/client-data?bogus=1").status_code == 200
    assert "bogus" not in service.calls[0][1]


def test_history_needs_one_identifier(harness) -> None:
    client, service, _ = harness

    response = client.get("/api/client-data/history")

    assert response.status_code == 400
    assert "ip_address" in response.json()["detail"]
    assert service.calls == []


@pytest.mark.parametrize(
    "query",
    [
        "mac_address=aabb&ip_address=10.0.0.5",
        "ip_address=1.1.1.1&hostname=pc1",
        "mac_address=a&ip_address=b&hostname=c",
    ],
)
def test_history_takes_exactly_one_identifier(harness, query: str) -> None:
    client, service, _ = harness

    response = client.get(f"/api/client-data/history?{query}")

    assert response.status_code == 400
    assert "exactly one" in response.json()["detail"]
    assert service.calls == []


def test_ip_prefix_is_passed_through(harness) -> None:
    client, service, _ = harness

    client.get("/api/client-data?ip_prefix=10.1.")

    assert service.calls[0][1]["ip_prefix"] == "10.1."


def test_history_returns_the_observations(harness) -> None:
    client, service, _ = harness

    response = client.get("/api/client-data/history?mac_address=AA:BB:CC:DD:00:01&limit=5")

    assert response.status_code == 200
    assert response.json()["mac_history"][0]["port"] == "Gi1/0/5"
    assert service.calls[0][1]["limit"] == 5


@pytest.mark.parametrize("limit", [0, 1001])
def test_history_limit_is_bounded(harness, limit: int) -> None:
    client, _, _ = harness

    response = client.get(f"/api/client-data/history?mac_address=aabb&limit={limit}")

    assert response.status_code == 422


def test_devices_lists_the_newest_collection_of_each_device(harness) -> None:
    client, _, _ = harness

    response = client.get("/api/client-data/devices")

    assert response.status_code == 200
    (device,) = response.json()
    assert (device["device_name"], device["vrf_status"], device["mac_rows"]) == (
        "swB",
        "not_supported",
        20,
    )
    assert device["vrfs"] == [{"name": "CUST", "status": "ok", "rows": 0}]
    assert device["mac_collected_at"] < device["arp_collected_at"]
