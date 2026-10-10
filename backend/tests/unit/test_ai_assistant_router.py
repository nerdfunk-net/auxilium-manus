"""TestClient tests for /ai/*: enable switch enforced server-side, key write-only, SSE framing."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from _ai_helpers import FakeRepo
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.config import settings
from core.crypto import EncryptionService
from core.database import get_db
from core.models.users import User
from repositories.plugin_repository import PluginRepository
from routers import ai_assistant as ai_router_module
from routers.ai_assistant import get_ai_settings_service, router
from services.ai_assistant.chat_service import ChatEvent
from services.ai_assistant.settings_service import AiSettingsService
from services.auth.rbac_service import RBACService
from services.plugin_registry.plugin_registry_service import PluginRegistryService

SECRET = "sk-ant-router-secret"


def _user(user_id: int = 1) -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = user_id
    return user


SESSIONS: list[MagicMock] = []


def _override_db() -> Iterator[MagicMock]:
    db = make_auth_db()
    SESSIONS.append(db)
    yield db


@pytest.fixture(autouse=True)
def _reset_sessions() -> None:
    SESSIONS.clear()


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def allowed(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    state = {"value": True}
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: state["value"])
    return state


@pytest.fixture
def client(repo: FakeRepo, allowed: dict[str, bool]) -> TestClient:
    service = AiSettingsService(repo, EncryptionService("test-secret-key-for-ai-router-0000"))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: _user(1)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_ai_settings_service] = lambda: service
    return TestClient(app)


def _configure(client: TestClient, *, enabled: bool = True) -> None:
    response = client.patch("/api/ai/settings", json={"api_key": SECRET, "enabled": enabled})
    assert response.status_code == 200, response.text


def test_status_reports_each_reason(client: TestClient, allowed: dict[str, bool]) -> None:
    allowed["value"] = False
    assert client.get("/api/ai/status").json() == {"available": False, "reason": "no_permission"}

    allowed["value"] = True
    assert client.get("/api/ai/status").json()["reason"] == "disabled"

    client.patch("/api/ai/settings", json={"enabled": True})
    assert client.get("/api/ai/status").json()["reason"] == "not_configured"

    client.patch("/api/ai/settings", json={"api_key": SECRET})
    assert client.get("/api/ai/status").json() == {"available": True, "reason": "ok"}


def test_settings_require_permission(client: TestClient, allowed: dict[str, bool]) -> None:
    allowed["value"] = False

    assert client.get("/api/ai/settings").status_code == 403
    assert client.patch("/api/ai/settings", json={"enabled": True}).status_code == 403


def test_key_is_never_returned(client: TestClient) -> None:
    patched = client.patch("/api/ai/settings", json={"api_key": SECRET})
    fetched = client.get("/api/ai/settings")

    for response in (patched, fetched):
        assert SECRET not in response.text
        assert response.json()["api_key_set"] is True


def test_custom_base_url_requires_admin(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"provider": "openai_compat", "model": "m", "base_url": "http://10.0.0.5:11434/v1"}
    monkeypatch.setattr(RBACService, "has_role", lambda self, *_a, **_k: False)

    denied = client.patch("/api/ai/settings", json=body)

    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "ai_base_url_admin_only"
    # Everything else stays available to a plain user.
    assert client.patch("/api/ai/settings", json={"enabled": True}).status_code == 200


def test_unknown_fields_and_unavailable_provider_are_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_role", lambda self, *_a, **_k: True)
    assert client.patch("/api/ai/settings", json={"surprise": 1}).status_code == 422
    assert client.patch("/api/ai/settings", json={"provider": "nonsense"}).status_code == 422
    rejected = client.patch(
        "/api/ai/settings",
        json={"provider": "openai_compat", "base_url": "http://169.254.169.254/v1"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "ai_settings_invalid"


def test_chat_is_refused_server_side_when_disabled(client: TestClient) -> None:
    _configure(client, enabled=False)

    response = client.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ai_assistant_disabled"


def test_chat_streams_sse_events(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(client)
    seen: dict[str, object] = {}

    async def fake_stream(config, messages, **kwargs):
        seen["model"] = config.model
        seen["messages"] = [(m.role, m.content) for m in messages]
        yield ChatEvent("text", {"text": "Hello"})
        yield ChatEvent("done", {})

    monkeypatch.setattr(ai_router_module, "stream_chat", fake_stream)

    response = client.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == ('event: text\ndata: {"text": "Hello"}\n\nevent: done\ndata: {}\n\n')
    assert seen["messages"] == [("user", "hi")]
    assert SECRET not in response.text


def test_chat_validates_the_request_body(client: TestClient) -> None:
    _configure(client)

    assert client.post("/api/ai/chat", json={"messages": []}).status_code == 422
    bad_role = {"messages": [{"role": "system", "content": "x"}]}
    assert client.post("/api/ai/chat", json=bad_role).status_code == 422


def test_connection_test_works_before_enabling(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client, enabled=False)

    async def fake_check(config):
        return {"ok": True}

    monkeypatch.setattr(ai_router_module, "check_connection", fake_check)

    assert client.post("/api/ai/settings/test").json() == {"ok": True}


def test_connection_test_without_key_is_a_conflict(client: TestClient) -> None:
    response = client.post("/api/ai/settings/test")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ai_assistant_not_configured"


def _dependency_names(route: APIRoute) -> set[str]:
    names: set[str] = set()

    def walk(dependant) -> None:
        for sub in dependant.dependencies:
            names.add(getattr(sub.call, "__name__", ""))
            walk(sub)

    walk(route.dependant)
    return names


def test_provider_calling_routes_are_rate_limited() -> None:
    by_path = {r.path: r for r in router.routes if isinstance(r, APIRoute)}

    assert "rate_limited_ai-chat" in _dependency_names(by_path["/ai/chat"])
    assert "rate_limited_ai-test" in _dependency_names(by_path["/ai/settings/test"])


def test_chat_releases_the_db_session_before_streaming(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client)
    closed_when_stream_started: list[bool] = []

    async def fake_stream(config, messages, **kwargs):
        closed_when_stream_started.append(SESSIONS[-1].close.called)
        yield ChatEvent("done", {})

    monkeypatch.setattr(ai_router_module, "stream_chat", fake_stream)

    client.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]})

    assert closed_when_stream_started == [True]


def test_connection_test_releases_the_db_session_before_the_provider_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client)
    closed_at_call: list[bool] = []

    async def fake_check(config):
        closed_at_call.append(SESSIONS[-1].close.called)
        return {"ok": True}

    monkeypatch.setattr(ai_router_module, "check_connection", fake_check)

    client.post("/api/ai/settings/test")

    assert closed_at_call == [True]


def test_chat_with_editor_context_gets_the_template_tools_and_prompt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client)
    seen: dict[str, object] = {}

    async def fake_stream(config, messages, **kwargs):
        seen["tools"] = [spec.name for spec in kwargs["toolbox"].specs()]
        seen["system"] = kwargs["system"]
        yield ChatEvent("done", {})

    monkeypatch.setattr(ai_router_module, "stream_chat", fake_stream)

    body = {
        "messages": [{"role": "user", "content": "add ntp"}],
        "context": {
            "surface": "template_editor",
            "name": "Base",
            "content": "hostname {{ device.name }}",
            "variables": [
                {"name": "nautobot", "type": "auto", "value": "DEVICE-DATA", "is_auto": True}
            ],
        },
    }
    response = client.post("/api/ai/chat", json=body)

    assert response.status_code == 200
    assert "propose_template" in seen["tools"]
    assert "DEVICE-DATA" not in str(seen["system"])
    assert "hostname {{ device.name }}" in str(seen["system"])


def test_chat_rejects_an_unknown_surface_or_oversized_content(client: TestClient) -> None:
    _configure(client)
    msg = [{"role": "user", "content": "hi"}]

    unknown = client.post("/api/ai/chat", json={"messages": msg, "context": {"surface": "x"}})
    huge = client.post(
        "/api/ai/chat",
        json={
            "messages": msg,
            "context": {"surface": "template_editor", "content": "a" * 200001},
        },
    )

    assert unknown.status_code == 422 and huge.status_code == 422


def test_chat_with_workflow_context_gets_the_workflow_tools(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client)
    seen: dict[str, object] = {}

    async def fake_stream(config, messages, **kwargs):
        seen["tools"] = [spec.name for spec in kwargs["toolbox"].specs()]
        seen["system"] = kwargs["system"]
        yield ChatEvent("done", {})

    monkeypatch.setattr(ai_router_module, "stream_chat", fake_stream)
    client.app.state.plugin_service = PluginRegistryService(  # type: ignore[attr-defined]
        PluginRepository(plugins_file=settings.plugins_file)
    )

    body = {
        "messages": [{"role": "user", "content": "add attributes"}],
        "context": {
            "surface": "workflow_editor",
            "name": "Backups",
            "canvas_nodes": [],
            "canvas_edges": [],
        },
    }
    response = client.post("/api/ai/chat", json=body)

    assert response.status_code == 200
    assert "propose_workflow" in seen["tools"] and "propose_template" not in seen["tools"]
    assert "<canvas_state>" in str(seen["system"])


def test_workflow_context_without_a_plugin_registry_is_a_503(client: TestClient) -> None:
    _configure(client)
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "context": {"surface": "workflow_editor"},
    }

    response = client.post("/api/ai/chat", json=body)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "plugin_registry_unavailable"


def test_oversized_workflow_canvas_is_rejected(client: TestClient) -> None:
    _configure(client)
    huge = [{"id": f"n{i}", "data": {"blob": "x" * 20000}} for i in range(200)]
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "context": {"surface": "workflow_editor", "canvas_nodes": huge},
    }

    assert client.post("/api/ai/chat", json=body).status_code == 422


def _capture_chat(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    seen: dict[str, object] = {}

    async def fake_stream(config, messages, **kwargs):
        seen["tools"] = [spec.name for spec in kwargs["toolbox"].specs()]
        seen["system"] = kwargs["system"]
        yield ChatEvent("done", {})

    monkeypatch.setattr(ai_router_module, "stream_chat", fake_stream)
    return seen


def test_run_viewer_context_gets_read_only_run_tools(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client)
    seen = _capture_chat(monkeypatch)

    body = {
        "messages": [{"role": "user", "content": "why did it fail"}],
        "context": {"surface": "run_viewer", "run_id": 5},
    }
    response = client.post("/api/ai/chat", json=body)

    assert response.status_code == 200
    assert "get_step_result" in seen["tools"] and "propose_workflow" not in seen["tools"]
    assert "run 5 open" in str(seen["system"])
    assert "shares with you: nothing" in str(seen["system"])


def test_saved_data_sharing_switches_reach_the_run_surface(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client)
    client.patch("/api/ai/settings", json={"share_content_data": True})
    seen = _capture_chat(monkeypatch)

    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "context": {"surface": "run_viewer"},
    }
    client.post("/api/ai/chat", json=body)

    assert "shares with you: run and device content" in str(seen["system"])


def test_run_viewer_rejects_a_bad_run_id(client: TestClient) -> None:
    _configure(client)
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "context": {"surface": "run_viewer", "run_id": 0},
    }

    assert client.post("/api/ai/chat", json=body).status_code == 422


def test_inventory_context_gets_the_inventory_tools(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client)
    seen = _capture_chat(monkeypatch)

    body = {
        "messages": [{"role": "user", "content": "how many core switches"}],
        "context": {"surface": "inventory", "source_id": "nb"},
    }
    response = client.post("/api/ai/chat", json=body)

    assert response.status_code == 200
    assert "resolve_inventory" in seen["tools"] and "propose_workflow" not in seen["tools"]
    assert "nothing about individual devices" in str(seen["system"])


def test_inventory_context_requires_a_source(client: TestClient) -> None:
    _configure(client)
    body = {"messages": [{"role": "user", "content": "hi"}], "context": {"surface": "inventory"}}

    assert client.post("/api/ai/chat", json=body).status_code == 422
