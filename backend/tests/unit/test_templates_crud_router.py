"""TestClient tests for POST/PUT /templates: the Markdown `notes` (wiki) field
is forwarded to the service and echoed back, and the length cap is enforced."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from routers.templates import _service
from routers.templates import router as templates_router
from services.auth.rbac_service import RBACService


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


def _template_dict(**overrides: object) -> dict:
    base = {
        "id": 1,
        "name": "tpl",
        "source": "webeditor",
        "template_type": "jinja2",
        "category": "netmiko",
        "description": None,
        "notes": None,
        "content": "",
        "variables": {},
        "pre_run_commands": [],
        "pre_run_use_textfsm": False,
        "nautobot_attributes": [],
        "credential_id": None,
        "created_by": "tester",
        "is_active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


@pytest.fixture
def service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, service: MagicMock) -> Iterator[TestClient]:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(templates_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client


def test_create_forwards_notes_to_service(client: TestClient, service: MagicMock) -> None:
    service.create_template.return_value = _template_dict(notes="# Wiki\nbody")

    response = client.post(
        "/api/templates",
        json={"name": "tpl", "notes": "# Wiki\nbody"},
    )

    assert response.status_code == 201
    assert response.json()["notes"] == "# Wiki\nbody"
    assert service.create_template.call_args.kwargs["notes"] == "# Wiki\nbody"


def test_update_forwards_notes_to_service(client: TestClient, service: MagicMock) -> None:
    service.update_template.return_value = _template_dict(notes="updated")

    response = client.put("/api/templates/1", json={"notes": "updated"})

    assert response.status_code == 200
    assert response.json()["notes"] == "updated"
    assert service.update_template.call_args.kwargs["notes"] == "updated"


def test_update_notes_over_length_cap_returns_422(
    client: TestClient, service: MagicMock
) -> None:
    response = client.put("/api/templates/1", json={"notes": "x" * 100_001})

    assert response.status_code == 422
    service.update_template.assert_not_called()
