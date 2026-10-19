"""FastAPI TestClient tests for /credentials scoping and enforcement."""

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
from routers.credentials import _service
from routers.credentials import router as credentials_router
from services.auth.rbac_service import RBACService
from services.credentials.exceptions import CredentialInUseError, CredentialNotFoundError
from services.credentials.usage import CredentialDependant


def _make_user(user_id: int = 1) -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = user_id
    return user


def _override_db() -> Iterator[MagicMock]:
    yield make_auth_db()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(credentials_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: token_payload()
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
            json={"name": "my-cred", "username": "admin", "password": "secret-pass-1"},
        )

    assert response.status_code == 201
    _, kwargs = mock_service.create_credential.call_args
    assert kwargs["visibility"] == "private"
    assert kwargs["acting_user_id"] == 1


def test_create_shared_secret_credential_passes_algorithm(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.create_credential.return_value = {
        "id": 2,
        "name": "vault-key",
        "username": "vault-key",
        "type": "shared_secret",
        "algorithm": "aes-256-gcm",
        "valid_until": None,
        "is_active": True,
        "source": "general",
        "owner": None,
        "owner_user_id": None,
        "owner_username": None,
        "visibility": "global",
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
            json={
                "name": "vault-key",
                "username": "vault-key",
                "type": "shared_secret",
                "password": "the-passphrase",
                "algorithm": "aes-256-gcm",
                "visibility": "global",
            },
        )

    assert response.status_code == 201, response.text
    assert response.json()["algorithm"] == "aes-256-gcm"
    _, kwargs = mock_service.create_credential.call_args
    assert kwargs["algorithm"] == "aes-256-gcm"
    assert kwargs["cred_type"] == "shared_secret"


def test_create_shared_secret_credential_rejects_unknown_algorithm(app: FastAPI) -> None:
    mock_service = MagicMock()
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post(
            "/api/credentials",
            json={
                "name": "vault-key",
                "username": "vault-key",
                "type": "shared_secret",
                "password": "password-1234",
                "algorithm": "rot13",
            },
        )

    assert response.status_code == 422


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
    mock_service.delete_credential.assert_called_once_with(99, acting_user_id=1, force=False)


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


def test_short_secrets_are_rejected() -> None:
    """S3-15: tokens and shared secrets keep a length floor.

    SSH logins and Basic Auth secrets do not. The remote system owns that policy;
    a partial update that omits ``type`` still uses the common floor.
    """
    from pydantic import ValidationError

    from models.credentials import CredentialCreate, CredentialUpdate

    CredentialCreate(name="n", username="u", type="generic", password="1234567")
    CredentialCreate(name="n", username="u", type="ssh", password="abc")
    CredentialUpdate(type="ssh", password="abc")
    CredentialUpdate(type="generic", password="x")
    with pytest.raises(ValidationError):
        CredentialCreate(name="n", username="u", type="token", password="1234567")
    with pytest.raises(ValidationError):
        CredentialCreate(name="n", username="u", type="tacacs", password="1234567")
    CredentialCreate(name="n", username="u", type="tacacs", password="12345678")
    with pytest.raises(ValidationError):
        CredentialCreate(name="n", username="u", type="shared_secret", password="x")
    with pytest.raises(ValidationError):
        CredentialCreate(name="n", username="u", type="shared_secret", password="x" * 11)
    CredentialCreate(name="n", username="u", type="token", password="12345678")
    CredentialCreate(name="n", username="u", type="shared_secret", password="x" * 12)
    with pytest.raises(ValidationError):
        CredentialUpdate(password="1234567")


def test_delete_credential_in_use_returns_409_with_dependants(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.delete_credential.side_effect = CredentialInUseError(
        [CredentialDependant("git_repository", 3, "configs")]
    )
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.delete("/api/credentials/5")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "credential_in_use"
    assert detail["dependants"] == [{"kind": "git_repository", "id": 3, "name": "configs"}]
    mock_service.delete_credential.assert_called_once_with(5, acting_user_id=1, force=False)


def test_delete_credential_force_flag_is_passed_through(app: FastAPI) -> None:
    mock_service = MagicMock()
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.delete("/api/credentials/5?force=true")

    assert response.status_code == 204
    mock_service.delete_credential.assert_called_once_with(5, acting_user_id=1, force=True)
