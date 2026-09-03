"""FastAPI TestClient tests for GET /general/settings permission gating."""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from models.general_settings import GeneralSettingsResponse
from routers.general_settings import _service
from routers.general_settings import router as general_settings_router
from services.auth.rbac_service import RBACService


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(general_settings_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db
    mock_service = MagicMock()
    mock_service.get_settings.return_value = GeneralSettingsResponse(
        session_timeout_minutes=20,
        default_export_directory="",
        switch_to_runs_on_start=True,
        resolved_export_directory="/data/exports",
    )
    app.dependency_overrides[_service] = lambda: mock_service
    return app


def test_get_settings_denied_without_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)

    with TestClient(app) as client:
        response = client.get("/api/general/settings")

    assert response.status_code == 403


def test_get_settings_allowed_with_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)

    with TestClient(app) as client:
        response = client.get("/api/general/settings")

    assert response.status_code == 200
    assert response.json()["session_timeout_minutes"] == 20


def test_handlers_run_in_threadpool_not_on_the_event_loop() -> None:
    # FABLE_BACKEND_20260902.md §4.2: sync-only handlers must be plain `def` so
    # FastAPI offloads their blocking SQLAlchemy work to the threadpool.
    from routers.general_settings import get_general_settings, update_general_settings

    assert not inspect.iscoroutinefunction(get_general_settings)
    assert not inspect.iscoroutinefunction(update_general_settings)
