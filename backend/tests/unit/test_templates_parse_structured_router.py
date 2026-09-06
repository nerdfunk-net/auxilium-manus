"""TestClient tests for POST /templates/parse-structured."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from routers.templates import router as templates_router
from services.auth.rbac_service import RBACService


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(templates_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as test_client:
        yield test_client


def test_parses_yaml(client: TestClient) -> None:
    response = client.post(
        "/api/templates/parse-structured", json={"content": "a: 1\nb: two", "format": "yaml"}
    )
    assert response.status_code == 200
    assert response.json()["parsed"] == {"a": 1, "b": "two"}


def test_parses_json_auto(client: TestClient) -> None:
    response = client.post(
        "/api/templates/parse-structured", json={"content": '{"a": 1}', "format": "auto"}
    )
    assert response.status_code == 200
    assert response.json()["parsed"] == {"a": 1}


def test_invalid_content_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/templates/parse-structured", json={"content": "a: [1, 2", "format": "yaml"}
    )
    assert response.status_code == 422
