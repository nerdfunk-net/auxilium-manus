"""``sources.batfish:query`` implies listing: a user who may run ad-hoc Batfish queries can list the
sources, networks and snapshots the query form needs, but still cannot change a source."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_batfish_source_config_service
from routers.sources.batfish import (
    batfish_source_crud_router,
    batfish_source_discovery_router,
)
from services.auth.rbac_service import RBACService


def _user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _db() -> Iterator[MagicMock]:
    yield make_auth_db()


def _client(monkeypatch: pytest.MonkeyPatch, granted: set[str]) -> TestClient:
    monkeypatch.setattr(
        RBACService,
        "has_permission",
        lambda self, _uid, resource, action: resource == "sources.batfish" and action in granted,
    )
    service = MagicMock()
    service.list_sources.return_value = []
    app = FastAPI()
    app.include_router(batfish_source_crud_router, prefix="/api")
    app.include_router(batfish_source_discovery_router, prefix="/api")
    app.dependency_overrides[get_batfish_source_config_service] = lambda: service
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return TestClient(app, raise_server_exceptions=False)


def test_query_alone_lists_the_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, {"query"}) as client:
        assert client.get("/api/sources/batfish").status_code == 200


def test_read_alone_still_lists_the_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, {"read"}) as client:
        assert client.get("/api/sources/batfish").status_code == 200


def test_neither_permission_is_refused_and_both_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, set()) as client:
        response = client.get("/api/sources/batfish")
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "sources.batfish:read" in detail and "sources.batfish:query" in detail


def test_query_alone_cannot_create_or_delete_a_source(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, {"query"}) as client:
        created = client.post("/api/sources/batfish", json={"source_id": "lab", "host": "bf"})
        deleted = client.delete("/api/sources/batfish/lab")
    assert created.status_code == 403
    assert deleted.status_code == 403


@pytest.mark.parametrize("path", ["/lab/networks", "/lab/networks/prod/snapshots"])
def test_query_alone_lists_networks_and_snapshots(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    with _client(monkeypatch, {"query"}) as client:
        response = client.get(f"/api/sources/batfish{path}")
    # Past the permission gate; what the unmocked Batfish client answers is not the point here.
    assert response.status_code != 403


def test_no_permission_is_refused_for_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, set()) as client:
        assert client.get("/api/sources/batfish/lab/networks").status_code == 403
