"""FastAPI TestClient tests for the Batfish networks/snapshots discovery
endpoints (routers/sources/batfish/discovery.py).
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_batfish_source_config_service
from routers.sources.batfish import batfish_source_discovery_router
from services.auth.rbac_service import RBACService
from services.batfish.common.exceptions import BatfishAPIError
from services.batfish.source_config_service import BatfishSourceNotFoundError


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(batfish_source_discovery_router, prefix="/api")
    return app


@pytest.fixture
def app() -> FastAPI:
    return _build_app()


def _authenticate(app: FastAPI, *, config_service: MagicMock) -> None:
    app.dependency_overrides[get_batfish_source_config_service] = lambda: config_service
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db


def test_list_networks_requires_auth(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/api/sources/batfish/lab/networks")
    assert response.status_code == 401


def test_list_networks_forbidden_without_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)
    _authenticate(app, config_service=MagicMock())

    with TestClient(app) as client:
        response = client.get("/api/sources/batfish/lab/networks")

    assert response.status_code == 403
    assert "sources.batfish:read" in response.json()["detail"]


def test_list_networks_success_sorted(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    mock_config_service = MagicMock()
    mock_config_service.resolve_connection.return_value = MagicMock()
    _authenticate(app, config_service=mock_config_service)

    import service_factory

    mock_batfish = MagicMock()

    async def _list_networks(*_a, **_k):
        return ["manus-workflow-2", "manus-workflow-1"]

    mock_batfish.list_networks = _list_networks
    monkeypatch.setattr(service_factory, "get_batfish_app_service", lambda: mock_batfish)

    with TestClient(app) as client:
        response = client.get("/api/sources/batfish/lab/networks")

    assert response.status_code == 200
    assert response.json()["networks"] == ["manus-workflow-1", "manus-workflow-2"]


def test_list_networks_source_not_found_maps_to_404(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    mock_config_service = MagicMock()
    mock_config_service.resolve_connection.side_effect = BatfishSourceNotFoundError("lab")
    _authenticate(app, config_service=mock_config_service)

    with TestClient(app) as client:
        response = client.get("/api/sources/batfish/lab/networks")

    assert response.status_code == 404


def test_list_networks_api_error_maps_to_sanitized_502(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    mock_config_service = MagicMock()
    mock_config_service.resolve_connection.return_value = MagicMock()
    _authenticate(app, config_service=mock_config_service)

    import service_factory

    mock_batfish = MagicMock()

    async def _list_networks(*_a, **_k):
        raise BatfishAPIError("coordinator down: boom")

    mock_batfish.list_networks = _list_networks
    monkeypatch.setattr(service_factory, "get_batfish_app_service", lambda: mock_batfish)

    with TestClient(app) as client:
        response = client.get("/api/sources/batfish/lab/networks")

    assert response.status_code == 502
    body = response.json()["detail"]
    assert "boom" not in body["message"]
    assert "error_id" in body


def test_list_snapshots_success_sorted_most_recent_first(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    mock_config_service = MagicMock()
    mock_config_service.resolve_connection.return_value = MagicMock()
    _authenticate(app, config_service=mock_config_service)

    import service_factory

    mock_batfish = MagicMock()

    async def _list_networks(*_a, **_k):
        return ["manus-workflow-1"]

    async def _list_snapshots(*_a, **_k):
        return [
            {"name": "run-1", "metadata": {"creationTimestamp": "2026-09-12T10:00:00Z"}},
            {"name": "run-2", "metadata": {"creationTimestamp": "2026-09-13T10:00:00Z"}},
            {"name": "run-no-timestamp", "metadata": {}},
        ]

    mock_batfish.list_networks = _list_networks
    mock_batfish.list_snapshots_with_metadata = _list_snapshots
    monkeypatch.setattr(service_factory, "get_batfish_app_service", lambda: mock_batfish)

    with TestClient(app) as client:
        response = client.get("/api/sources/batfish/lab/networks/manus-workflow-1/snapshots")

    assert response.status_code == 200
    snapshots = response.json()["snapshots"]
    assert [s["name"] for s in snapshots] == ["run-2", "run-1", "run-no-timestamp"]
    assert snapshots[-1]["created_at"] is None


def test_list_snapshots_unknown_network_returns_empty_without_touching_metadata_call(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The critical regression test: a network that doesn't exist yet must
    never reach list_snapshots_with_metadata (-> _get_session ->
    set_network()), which would silently CREATE it on the coordinator --
    exactly what happened when a picker's fallback text field queried this
    endpoint on every keystroke before this guard existed."""
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    mock_config_service = MagicMock()
    mock_config_service.resolve_connection.return_value = MagicMock()
    _authenticate(app, config_service=mock_config_service)

    import service_factory

    mock_batfish = MagicMock()

    async def _list_networks(*_a, **_k):
        return ["manus-workflow-1"]

    async def _list_snapshots_should_never_be_called(*_a, **_k):
        raise AssertionError(
            "list_snapshots_with_metadata must not be called for an unknown network"
        )

    mock_batfish.list_networks = _list_networks
    mock_batfish.list_snapshots_with_metadata = _list_snapshots_should_never_be_called
    monkeypatch.setattr(service_factory, "get_batfish_app_service", lambda: mock_batfish)

    with TestClient(app) as client:
        response = client.get("/api/sources/batfish/lab/networks/m/snapshots")

    assert response.status_code == 200
    assert response.json()["snapshots"] == []


def test_list_snapshots_source_not_found_maps_to_404(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    mock_config_service = MagicMock()
    mock_config_service.resolve_connection.side_effect = BatfishSourceNotFoundError("lab")
    _authenticate(app, config_service=mock_config_service)

    with TestClient(app) as client:
        response = client.get("/api/sources/batfish/lab/networks/manus-workflow-1/snapshots")

    assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__])
