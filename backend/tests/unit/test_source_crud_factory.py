"""build_source_crud_router: the shared CRUD ladder of the /sources/<type> routers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from routers.source_crud_factory import build_source_crud_router
from services.auth.rbac_service import RBACService


class FakeCreate(BaseModel):
    source_id: str
    url: str


class FakeUpdate(BaseModel):
    url: str | None = None


class FakeResponse(BaseModel):
    source_id: str | None = None
    url: str | None = None


class FakeList(BaseModel):
    sources: list[FakeResponse]
    total: int


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Invalid(Exception):
    pass


def _service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def harness(monkeypatch):
    service = _service()
    router = build_source_crud_router(
        source_type="x",
        display_name="Fake",
        permission_resource="sources.x",
        tag="sources-x",
        service_dependency=lambda: service,
        create_model=FakeCreate,
        update_model=FakeUpdate,
        response_model=FakeResponse,
        list_response_model=FakeList,
        not_found_error=NotFound,
        conflict_error=Conflict,
        validation_errors=(Invalid,),
        create_kwargs=lambda r: {"source_id": r.source_id, "url": r.url},
        update_kwargs=lambda r: {"url": r.url},
    )
    granted = {"read", "write", "delete"}
    monkeypatch.setattr(
        RBACService, "has_permission", lambda self, _uid, _res, action: action in granted
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, service, router, granted


def test_list_shape(harness) -> None:
    client, service, _, _ = harness
    service.list_sources.return_value = [{"source_id": "a", "url": "https://a"}]

    r = client.get("/api/sources/x")

    assert r.status_code == 200
    assert r.json() == {"sources": [{"source_id": "a", "url": "https://a"}], "total": 1}


def test_create_forwards_kwargs_and_returns_201(harness) -> None:
    client, service, _, _ = harness
    service.create_source.return_value = {"source_id": "a", "url": "https://a"}

    r = client.post("/api/sources/x", json={"source_id": "a", "url": "https://a"})

    assert r.status_code == 201
    service.create_source.assert_called_once_with(source_id="a", url="https://a")


def test_conflict_is_409(harness) -> None:
    client, service, _, _ = harness
    service.create_source.side_effect = Conflict("exists")

    r = client.post("/api/sources/x", json={"source_id": "a", "url": "u"})

    assert r.status_code == 409 and r.json()["detail"] == "exists"


@pytest.mark.parametrize("error", [Invalid("bad"), ValueError("bad")])
def test_validation_error_and_value_error_are_400(harness, error) -> None:
    client, service, _, _ = harness
    service.create_source.side_effect = error
    service.update_source.side_effect = error

    assert client.post("/api/sources/x", json={"source_id": "a", "url": "u"}).status_code == 400
    assert client.put("/api/sources/x/a", json={"url": "u"}).status_code == 400


def test_missing_source_is_404_for_get_put_delete(harness) -> None:
    client, service, _, _ = harness
    service.get_source.side_effect = NotFound("nope")
    service.update_source.side_effect = NotFound("nope")
    service.delete_source.side_effect = NotFound("nope")

    assert client.get("/api/sources/x/a").status_code == 404
    assert client.put("/api/sources/x/a", json={"url": "u"}).status_code == 404
    assert client.delete("/api/sources/x/a").status_code == 404


def test_delete_returns_204(harness) -> None:
    client, service, _, _ = harness

    r = client.delete("/api/sources/x/a")

    assert r.status_code == 204
    service.delete_source.assert_called_once_with("a")


def test_unexpected_error_is_a_sanitised_500(harness) -> None:
    client, service, _, _ = harness
    service.list_sources.side_effect = RuntimeError("secret-detail")
    service.get_source.side_effect = RuntimeError("secret-detail")

    for response in (client.get("/api/sources/x"), client.get("/api/sources/x/a")):
        assert response.status_code == 500
        assert "secret-detail" not in response.text
        assert set(response.json()["detail"]) == {"message", "error_id"}


def test_write_and_delete_need_their_own_permission(harness) -> None:
    client, service, _, granted = harness
    granted.discard("write")
    granted.discard("delete")
    service.list_sources.return_value = []

    assert client.get("/api/sources/x").status_code == 200
    assert client.post("/api/sources/x", json={"source_id": "a", "url": "u"}).status_code == 403
    assert client.put("/api/sources/x/a", json={"url": "u"}).status_code == 403
    assert client.delete("/api/sources/x/a").status_code == 403


def test_route_names_are_unique_per_source_type(harness) -> None:
    _, _, router, _ = harness

    assert {route.name for route in router.routes} == {
        "list_x_sources",
        "get_x_source",
        "create_x_source",
        "update_x_source",
        "delete_x_source",
    }
