"""FastAPI TestClient tests for POST /netmiko/get-configs."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from routers.netmiko import _credentials_service
from routers.netmiko import router as netmiko_router
from services.auth.rbac_service import RBACService
from services.network.netmiko.connection import ConfigResult, NetmikoConnectionError


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(netmiko_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db
    return app


def _payload() -> dict:
    return {
        "host": "10.0.0.1",
        "platform": "cisco_ios",
        "network_driver": "cisco_ios",
        "credential_id": 1,
    }


def test_get_configs_returns_parsed_running_and_startup(app: FastAPI) -> None:
    mock_credentials_service = MagicMock()
    mock_credentials_service.get_credential_by_id.return_value = {
        "type": "ssh",
        "username": "admin",
    }
    mock_credentials_service.get_decrypted_password.return_value = "secret"
    app.dependency_overrides[_credentials_service] = lambda: mock_credentials_service

    with patch("routers.netmiko.NetmikoService") as netmiko_cls, patch(
        "routers.netmiko.parse_cisco_config_text"
    ) as parse_text:
        netmiko = netmiko_cls.return_value

        async def _get_configs(**_kwargs):
            return ConfigResult(
                success=True,
                running_config="hostname router1",
                startup_config="hostname router1",
            )

        netmiko.get_configs.side_effect = _get_configs
        parse_text.side_effect = lambda content, _hint: {"hostname": "router1", "raw": content}

        with TestClient(app) as client:
            response = client.post("/api/netmiko/get-configs", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["parsed"]["running"]["hostname"] == "router1"
    assert body["parsed"]["startup"]["hostname"] == "router1"


def test_get_configs_connection_failure_returns_graceful_error(app: FastAPI) -> None:
    mock_credentials_service = MagicMock()
    mock_credentials_service.get_credential_by_id.return_value = {
        "type": "ssh",
        "username": "admin",
    }
    mock_credentials_service.get_decrypted_password.return_value = "secret"
    app.dependency_overrides[_credentials_service] = lambda: mock_credentials_service

    with patch("routers.netmiko.NetmikoService") as netmiko_cls:
        netmiko = netmiko_cls.return_value

        async def _raise(**_kwargs):
            raise NetmikoConnectionError("timed out")

        netmiko.get_configs.side_effect = _raise

        with TestClient(app) as client:
            response = client.post("/api/netmiko/get-configs", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"] == "timed out"


def test_get_configs_rejects_non_ssh_credential(app: FastAPI) -> None:
    mock_credentials_service = MagicMock()
    mock_credentials_service.get_credential_by_id.return_value = {
        "type": "api_key",
        "username": "admin",
    }
    app.dependency_overrides[_credentials_service] = lambda: mock_credentials_service

    with TestClient(app) as client:
        response = client.post("/api/netmiko/get-configs", json=_payload())

    assert response.status_code == 400
