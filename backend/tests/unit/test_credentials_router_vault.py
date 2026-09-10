"""Router-level behaviour for the vault storage backend."""

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
from services.credentials.exceptions import (
    CredentialVaultNotConfiguredError,
    CredentialVaultUnavailableError,
)


def _make_user(user_id: int = 1) -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = user_id
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    application = FastAPI()
    application.include_router(credentials_router, prefix="/api")
    application.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    application.dependency_overrides[get_current_user] = lambda: _make_user(1)
    application.dependency_overrides[get_db] = _override_db
    return application


@pytest.mark.parametrize("enabled", [False, True])
def test_vault_status_echoes_settings_flag(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "vault_enabled", enabled)
    with TestClient(app) as client:
        response = client.get("/api/credentials/vault/status")
    assert response.status_code == 200
    assert response.json() == {"enabled": enabled}


def _create_payload(**overrides) -> dict:
    payload = {
        "name": "vault-cred",
        "username": "svc",
        "type": "token",
        "password": "tok",
        "visibility": "global",
        "storage_backend": "vault",
    }
    payload.update(overrides)
    return payload


def test_create_vault_credential_without_backend_returns_422(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.create_credential.side_effect = CredentialVaultNotConfiguredError()
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post("/api/credentials", json=_create_payload())

    assert response.status_code == 422
    mock_service.create_credential.assert_called_once()
    assert mock_service.create_credential.call_args.kwargs["storage_backend"] == "vault"


def test_create_vault_credential_openbao_down_returns_503(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.create_credential.side_effect = CredentialVaultUnavailableError("sealed")
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post("/api/credentials", json=_create_payload())

    assert response.status_code == 503


def test_reveal_password_openbao_down_returns_503(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.get_decrypted_password.side_effect = CredentialVaultUnavailableError("down")
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.get("/api/credentials/5/password")

    assert response.status_code == 503


if __name__ == "__main__":
    import pytest as _pytest

    raise SystemExit(_pytest.main([__file__, "-q"]))
