"""FastAPI TestClient tests for auth/permission gating and error mapping on
the ad-hoc Batfish query endpoints (routers/sources/batfish/query.py).
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_batfish_preview_service
from models.batfish import BatfishQueryResponse
from routers.sources.batfish import batfish_source_query_router
from services.auth.rbac_service import RBACService
from services.batfish.common.exceptions import BatfishAPIError, BatfishValidationError
from services.batfish.source_config_service import BatfishSourceNotFoundError


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(batfish_source_query_router, prefix="/api")
    return app


@pytest.fixture
def app() -> FastAPI:
    return _build_app()


def _authenticate(app: FastAPI) -> None:
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db


def test_query_routes_requires_auth(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/sources/batfish/lab/query/routes", json={"network": "net"}
        )
    assert response.status_code == 401


def test_query_routes_forbidden_without_permission(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)
    _authenticate(app)

    with TestClient(app) as client:
        response = client.post(
            "/api/sources/batfish/lab/query/routes", json={"network": "net"}
        )

    assert response.status_code == 403
    assert "sources.batfish:read" in response.json()["detail"]


def test_query_routes_success(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    _authenticate(app)

    mock_service = MagicMock()
    mock_service.run_routes = AsyncMock(
        return_value=BatfishQueryResponse(
            success=True,
            question="routes",
            network="net",
            snapshot="run-1",
            rows=[],
        )
    )
    app.dependency_overrides[get_batfish_preview_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post(
            "/api/sources/batfish/lab/query/routes", json={"network": "net"}
        )

    assert response.status_code == 200
    assert response.json()["question"] == "routes"


def test_query_reachability_source_not_found_maps_to_404(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    _authenticate(app)

    mock_service = MagicMock()
    mock_service.run_reachability = AsyncMock(side_effect=BatfishSourceNotFoundError("lab"))
    app.dependency_overrides[get_batfish_preview_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post(
            "/api/sources/batfish/lab/query/reachability",
            json={"network": "net", "start_node": "R1"},
        )

    assert response.status_code == 404


def test_query_reachability_validation_error_maps_to_400(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    _authenticate(app)

    mock_service = MagicMock()
    mock_service.run_reachability = AsyncMock(
        side_effect=BatfishValidationError("start_node is required")
    )
    app.dependency_overrides[get_batfish_preview_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post(
            "/api/sources/batfish/lab/query/reachability",
            json={"network": "net", "start_node": "R1"},
        )

    assert response.status_code == 400


def test_query_test_filters_api_error_maps_to_sanitized_502(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    _authenticate(app)

    mock_service = MagicMock()
    mock_service.run_test_filters = AsyncMock(
        side_effect=BatfishAPIError("Batfish question 'testFilters' failed: boom")
    )
    app.dependency_overrides[get_batfish_preview_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post(
            "/api/sources/batfish/lab/query/test-filters",
            json={"network": "net", "node": "R1", "filter_name": "ACL", "dst_ips": "1.1.1.1"},
        )

    assert response.status_code == 502
    body = response.json()["detail"]
    # 5xx errors must never leak raw exception text (core/safe_http_errors.py).
    assert "boom" not in body["message"]
    assert "error_id" in body


def test_query_generic_success(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    _authenticate(app)

    mock_service = MagicMock()
    mock_service.run_generic = AsyncMock(
        return_value=BatfishQueryResponse(
            success=True,
            question="edges",
            network="net",
            snapshot="run-1",
            rows=[],
        )
    )
    app.dependency_overrides[get_batfish_preview_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post(
            "/api/sources/batfish/lab/query/generic",
            json={"network": "net", "question": "edges"},
        )

    assert response.status_code == 200
    assert response.json()["question"] == "edges"


def test_query_generic_non_allowlisted_question_maps_to_400(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    _authenticate(app)

    mock_service = MagicMock()
    mock_service.run_generic = AsyncMock(
        side_effect=ValueError("Batfish question 'dropTables' is not allow-listed")
    )
    app.dependency_overrides[get_batfish_preview_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post(
            "/api/sources/batfish/lab/query/generic",
            json={"network": "net", "question": "dropTables"},
        )

    assert response.status_code == 400
