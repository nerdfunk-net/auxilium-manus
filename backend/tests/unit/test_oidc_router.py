"""TestClient coverage for routers/oidc.py::handle_callback identity-conflict
mapping (doc/plans/FABE_BACKEND_ISSUES.md §1.5, §1.7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.oidc as oidc_router_module
from core.database import get_db
from dependencies import get_oidc_service
from routers.oidc import router as oidc_router
from services.auth.oidc_service import OIDCIdentityConflictError

REDIRECT_URI = "http://localhost:3000/login/callback"


class _FakeCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str, ttl_seconds: int) -> None:  # noqa: ARG002
        self._store[key] = value

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


@pytest.fixture
def ctx(monkeypatch):
    fake_cache = _FakeCache()
    monkeypatch.setattr(
        oidc_router_module.service_factory, "build_cache_service", lambda: fake_cache
    )

    app = FastAPI()
    app.include_router(oidc_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: MagicMock()

    oidc_service = MagicMock()
    oidc_service.generate_state.return_value = "state123"
    oidc_service.generate_authorization_url = AsyncMock(return_value="https://idp.example/auth")
    oidc_service.exchange_code_for_tokens = AsyncMock(return_value={"id_token": "token"})
    oidc_service.verify_id_token = AsyncMock(return_value={"sub": "abc123"})
    oidc_service.extract_user_data.return_value = {
        "username": "jdoe",
        "email": "jdoe@example.com",
        "sub": "abc123",
        "provider_id": "corporate",
    }
    app.dependency_overrides[get_oidc_service] = lambda: oidc_service

    with TestClient(app) as client:
        yield client, oidc_service, fake_cache


def _seed_state(fake_cache: _FakeCache, state: str, redirect_uri: str) -> None:
    fake_cache.set(f"oidc-state:{state}", redirect_uri, ttl_seconds=600)


class TestHandleCallback:
    def test_identity_conflict_returns_403_and_issues_no_token(self, ctx) -> None:
        client, oidc_service, fake_cache = ctx
        state = "corporate:state123"
        _seed_state(fake_cache, state, REDIRECT_URI)
        oidc_service.provision_or_get_user.side_effect = OIDCIdentityConflictError(
            "This identity cannot be linked to an existing account; ask an administrator"
        )

        response = client.post(
            "/api/auth/oidc/corporate/callback",
            json={"code": "authcode", "state": state, "redirect_uri": REDIRECT_URI},
        )

        assert response.status_code == 403
        assert "access_token" not in response.text

    def test_matched_identity_returns_token(self, ctx) -> None:
        client, oidc_service, fake_cache = ctx
        state = "corporate:state123"
        _seed_state(fake_cache, state, REDIRECT_URI)
        user = MagicMock(id=1, username="jdoe", token_version=0)
        oidc_service.provision_or_get_user.return_value = user

        response = client.post(
            "/api/auth/oidc/corporate/callback",
            json={"code": "authcode", "state": state, "redirect_uri": REDIRECT_URI},
        )

        assert response.status_code == 200
        assert "access_token" in response.json()
