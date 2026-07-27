"""FastAPI TestClient tests for /credentials scoping and enforcement."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from routers.credentials import _service
from routers.credentials import router as credentials_router
from services.auth.rbac_service import RBACService
from services.credentials.exceptions import CredentialNotFoundError


def _make_user(user_id: int = 1) -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = user_id
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(credentials_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: _make_user(1)
    app.dependency_overrides[get_db] = _override_db
    return app


def test_list_credentials_scopes_to_acting_user(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.list_credentials.return_value = []
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.get("/api/credentials")

    assert response.status_code == 200
    mock_service.list_credentials.assert_called_once_with(
        include_expired=False, source="general", acting_user_id=1
    )


def test_create_credential_defaults_to_private_and_passes_acting_user(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.create_credential.return_value = {
        "id": 1,
        "name": "my-cred",
        "username": "admin",
        "type": "ssh",
        "valid_until": None,
        "is_active": True,
        "source": "general",
        "owner": None,
        "owner_user_id": 1,
        "owner_username": None,
        "visibility": "private",
        "created_at": None,
        "updated_at": None,
        "status": "active",
        "has_password": True,
        "has_ssh_key": False,
        "has_ssh_passphrase": False,
    }
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post(
            "/api/credentials",
            json={"name": "my-cred", "username": "admin", "password": "secret"},
        )

    assert response.status_code == 201
    _, kwargs = mock_service.create_credential.call_args
    assert kwargs["visibility"] == "private"
    assert kwargs["acting_user_id"] == 1


def test_update_credential_returns_404_for_other_users_private_credential(
    app: FastAPI,
) -> None:
    mock_service = MagicMock()
    mock_service.update_credential.side_effect = CredentialNotFoundError(99)
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.put("/api/credentials/99", json={"name": "renamed"})

    assert response.status_code == 404


def test_delete_credential_returns_404_for_other_users_private_credential(
    app: FastAPI,
) -> None:
    mock_service = MagicMock()
    mock_service.delete_credential.side_effect = CredentialNotFoundError(99)
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.delete("/api/credentials/99")

    assert response.status_code == 404
    mock_service.delete_credential.assert_called_once_with(99, acting_user_id=1)


def test_get_credential_password_returns_404_for_other_users_private_credential(
    app: FastAPI,
) -> None:
    mock_service = MagicMock()
    mock_service.get_decrypted_password.side_effect = CredentialNotFoundError(99)
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.get("/api/credentials/99/password")

    assert response.status_code == 404
    mock_service.get_decrypted_password.assert_called_once_with(99, acting_user_id=1)
