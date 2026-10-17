"""Nautobot preview routes: a malformed filter value is a 400 with its message, not a 500."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.domain_exceptions import DomainError, InvalidFilterInputError
from core.models.users import User
from routers.sources.nautobot import ops
from services.auth.rbac_service import RBACService


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    monkeypatch.setattr(ops, "nautobot_credentials_from_source_ref", lambda *_a, **_k: MagicMock())
    service = MagicMock()
    monkeypatch.setattr(ops, "_build_source_service", lambda *_a, **_k: service)
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.include_router(ops.router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, service


def _preview_path(client: TestClient) -> str:
    for route in ops.router.routes:
        if getattr(route, "path", "").endswith("/preview"):
            return "/api" + route.path
    raise AssertionError("preview route not found")


_BODY = {
    "source_id": "lab",
    "operations": [
        {
            "operation_type": "AND",
            "conditions": [
                {"field": "prefix", "operator": "equals", "value": "10.0.0.0/8\"}"}
            ],
            "nested_operations": [],
        }
    ],
}


def test_preview_with_malformed_cidr_is_400_with_message(ctx):
    client, service = ctx
    service.preview_inventory = AsyncMock(side_effect=InvalidFilterInputError("invalid IP prefix"))
    response = client.post(_preview_path(client), json=_BODY)
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid IP prefix"


def test_other_errors_still_do_not_leak_text(ctx):
    client, service = ctx
    service.preview_inventory = AsyncMock(side_effect=RuntimeError("secret internal detail"))
    response = client.post(_preview_path(client), json=_BODY)
    assert response.status_code == 500
    assert "secret internal detail" not in response.text


def test_location_types_listing_maps_rest_payload(ctx, monkeypatch):
    client, _service = ctx
    from dependencies import nautobot_credentials_from_source_id

    client.app.dependency_overrides[nautobot_credentials_from_source_id] = lambda: MagicMock()
    types_service = MagicMock()
    types_service.list_location_types = AsyncMock(
        return_value=[
            {"id": "1", "name": "Country", "display": "Country", "parent": None},
            {
                "id": "2",
                "name": "State",
                "display": "Country → State",
                "parent": {"name": "Country"},
                "nestable": True,
            },
            {"id": "3", "name": ""},
            {"name": "NoId"},
        ]
    )
    monkeypatch.setattr(ops, "_build_location_types_service", lambda *_a, **_k: types_service)

    response = client.get("/api/sources/nautobot/location-types?source_id=s")

    assert response.status_code == 200
    assert response.json()["location_types"] == [
        {
            "id": "1",
            "name": "Country",
            "display": "Country",
            "parent_name": None,
            "nestable": False,
        },
        {
            "id": "2",
            "name": "State",
            "display": "Country → State",
            "parent_name": "Country",
            "nestable": True,
        },
    ]


def test_location_types_listing_failure_is_sanitised(ctx, monkeypatch):
    client, _service = ctx
    from dependencies import nautobot_credentials_from_source_id

    client.app.dependency_overrides[nautobot_credentials_from_source_id] = lambda: MagicMock()
    types_service = MagicMock()
    types_service.list_location_types = AsyncMock(side_effect=RuntimeError("secret-token"))
    monkeypatch.setattr(ops, "_build_location_types_service", lambda *_a, **_k: types_service)

    response = client.get("/api/sources/nautobot/location-types?source_id=s")

    assert response.status_code == 500
    assert "secret-token" not in response.text
