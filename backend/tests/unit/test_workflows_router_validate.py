"""FastAPI TestClient tests for POST /workflows/{id}/validate — draft-vs-saved
canvas_nodes selection, modeled on tests/unit/test_workflows_router_changes_and_notes.py."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from models.plugins import PluginRegistry
from routers.workflow_steps import get_plugin_service
from routers.workflows import _service
from routers.workflows import router as workflows_router
from services.auth.rbac_service import RBACService


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
    app.include_router(workflows_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: _make_user(1)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_plugin_service] = lambda: SimpleNamespace(
        get_registry=lambda: PluginRegistry(schema_version=1, plugins=[])
    )
    return app


def test_validate_workflow_uses_saved_canvas_nodes_by_default(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.get_workflow.return_value = SimpleNamespace(
        canvas_nodes=[{"id": "n1", "data": {"kind": "unknown-step"}}],
        canvas_edges=[],
    )
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post("/api/workflows/1/validate")

    assert response.status_code == 200
    body = response.json()
    assert body["has_errors"] is True
    assert body["findings"][0]["node_id"] == "n1"
    assert body["findings"][0]["code"] == "unknown_step_kind"
    mock_service.get_workflow.assert_called_once_with(workflow_id=1, user_id=1)


def test_validate_workflow_prefers_draft_canvas_nodes_from_body(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.get_workflow.return_value = SimpleNamespace(
        canvas_nodes=[{"id": "saved", "data": {"kind": "unknown-step"}}],
        canvas_edges=[],
    )
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post(
            "/api/workflows/1/validate",
            json={"canvas_nodes": [{"id": "draft", "data": {"kind": "unknown-step"}}]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["findings"][0]["node_id"] == "draft"


def test_validate_workflow_returns_no_findings_for_clean_canvas(app: FastAPI) -> None:
    mock_service = MagicMock()
    mock_service.get_workflow.return_value = SimpleNamespace(canvas_nodes=[], canvas_edges=[])
    app.dependency_overrides[_service] = lambda: mock_service

    with TestClient(app) as client:
        response = client.post("/api/workflows/1/validate", json={"canvas_nodes": []})

    assert response.status_code == 200
    assert response.json() == {"findings": [], "has_errors": False}


def test_validate_workflow_prefers_draft_canvas_edges_from_body(app: FastAPI) -> None:
    """Tier 3 needs edges: a step requiring a capability nothing upstream
    produces must be flagged even when the draft is unsaved."""
    mock_service = MagicMock()
    mock_service.get_workflow.return_value = SimpleNamespace(canvas_nodes=[], canvas_edges=[])
    app.dependency_overrides[_service] = lambda: mock_service
    app.dependency_overrides[get_plugin_service] = lambda: SimpleNamespace(
        get_registry=lambda: PluginRegistry(
            schema_version=1,
            plugins=[
                {
                    "id": "needs-identity",
                    "name": "Needs Identity",
                    "overview": "o",
                    "description": "d",
                    "artifact_type": "command_execution",
                    "directory": "needs_identity",
                    "requires": ["identity"],
                    "produces": [],
                    "outcomes": [{"name": "success"}],
                }
            ],
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/workflows/1/validate",
            json={
                "canvas_nodes": [{"id": "n1", "data": {"kind": "needs-identity"}}],
                "canvas_edges": [],
            },
        )

    assert response.status_code == 200
    body = response.json()
    tier3 = [f for f in body["findings"] if f["tier"] == 3]
    assert len(tier3) == 1
    assert tier3[0]["code"] == "missing_capability"
    assert tier3[0]["node_id"] == "n1"
