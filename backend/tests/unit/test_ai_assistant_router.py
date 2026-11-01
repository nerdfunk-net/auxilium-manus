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


def test_saving_settings_is_rate_limited() -> None:
    patch_route = next(
        r for r in router.routes if isinstance(r, APIRoute) and r.methods == {"PATCH"}
    )
    get_route = next(
        r
        for r in router.routes
        if isinstance(r, APIRoute) and r.path == "/ai/settings" and r.methods == {"GET"}
    )

    assert "rate_limited_ai-settings" in _dependency_names(patch_route)
    assert "rate_limited_ai-settings" not in _dependency_names(get_route)


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


def _workflow_chat(client: TestClient, monkeypatch: pytest.MonkeyPatch, granted: set[str]):
    """Post a workflow-editor chat where the user holds only ``granted`` workflows:* actions."""
    _configure(client)
    seen: dict[str, object] = {}

    async def fake_stream(config, messages, **kwargs):
        seen["tools"] = [spec.name for spec in kwargs["toolbox"].specs()]
        yield ChatEvent("done", {})

    monkeypatch.setattr(ai_router_module, "stream_chat", fake_stream)
    monkeypatch.setattr(
        RBACService,
        "has_permission",
        lambda self, _uid, resource, action: resource != "workflows" or action in granted,
    )
    client.app.state.plugin_service = PluginRegistryService(  # type: ignore[attr-defined]
        PluginRepository(plugins_file=settings.plugins_file)
    )
    body = {
        "messages": [{"role": "user", "content": "add attributes"}],
        "context": {"surface": "workflow_editor", "canvas_nodes": [], "canvas_edges": []},
    }
    return client.post("/api/ai/chat", json=body), seen


def test_workflow_surface_requires_workflows_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    response, seen = _workflow_chat(client, monkeypatch, granted=set())

    assert response.status_code == 403
    assert "tools" not in seen


def test_propose_workflow_tool_absent_without_write(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    response, seen = _workflow_chat(client, monkeypatch, granted={"read"})

    assert response.status_code == 200
    assert "validate_workflow" in seen["tools"] and "propose_workflow" not in seen["tools"]


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


@pytest.mark.parametrize("may_save", [True, False])
def test_inventory_proposal_tool_needs_permission_to_save_inventories(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, may_save: bool
) -> None:
    _configure(client)
    seen = _capture_chat(monkeypatch)
    monkeypatch.setattr(
        RBACService,
        "has_permission",
        lambda self, _uid, resource, action: (
            (resource, action) != ("sources.nautobot", "write") or may_save
        ),
    )
    body = {
        "messages": [{"role": "user", "content": "make an inventory"}],
        "context": {
            "surface": "inventory",
            "source_id": "nb",
            "filter_tree": {"type": "root", "internalLogic": "AND", "items": []},
        },
    }

    response = client.post("/api/ai/chat", json=body)

    assert response.status_code == 200
    assert ("propose_inventory" in seen["tools"]) is may_save
    assert "preview_filter" in seen["tools"]
    assert "current filter is empty" in str(seen["system"])


def test_inventory_context_requires_a_source(client: TestClient) -> None:
    _configure(client)
    body = {"messages": [{"role": "user", "content": "hi"}], "context": {"surface": "inventory"}}

    assert client.post("/api/ai/chat", json=body).status_code == 422


def test_reports_context_gets_report_tools_and_catalog_only_by_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client)
    seen = _capture_chat(monkeypatch)

    body = {
        "messages": [{"role": "user", "content": "devices per site?"}],
        "context": {"surface": "reports"},
    }
    response = client.post("/api/ai/chat", json=body)

    assert response.status_code == 200
    assert "propose_query" in seen["tools"] and "propose_workflow" not in seen["tools"]
    assert "no report values" in str(seen["system"])


def test_report_data_switch_is_saved_and_reaches_the_reports_surface(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client)
    saved = client.patch("/api/ai/settings", json={"share_report_data": True})
    seen = _capture_chat(monkeypatch)

    client.post(
        "/api/ai/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "context": {"surface": "reports"}},
    )

    assert saved.json()["share_report_data"] is True
    assert "shares with you: report values" in str(seen["system"])


def test_ai_surface_is_404_when_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ai_router_module.settings, "ai_assistant_enabled", False)

    assert client.get("/api/ai/settings").status_code == 404
    assert client.post("/api/ai/chat", json={"messages": []}).status_code == 404
    status_response = client.get("/api/ai/status")
    assert status_response.status_code == 200
    assert status_response.json()["reason"] == "operator_disabled"


class _FakeProxyService:
    saved: dict[str, object] | None = None

    def __init__(self, _db: object) -> None:
        pass

    def get(self) -> object:
        from models.ai_assistant import AiProxySettingsResponse

        return AiProxySettingsResponse(
            enabled=True,
            url="http://10.1.1.1:3128",
            credential_id=3,
            credential_name="corp-proxy",
            bypass_hosts=[],
            configured=True,
        )

    def update(self, data: object, *, actor_user_id: int | None = None) -> object:
        _FakeProxyService.saved = {**data.model_dump(), "actor": actor_user_id}  # type: ignore[attr-defined]
        return self.get()


def test_proxy_endpoints_require_admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_router_module, "AiProxySettingsService", _FakeProxyService)
    monkeypatch.setattr(RBACService, "has_role", lambda self, *_a, **_k: False)

    assert client.get("/api/ai/proxy").status_code == 403
    assert client.put("/api/ai/proxy", json={"enabled": False}).status_code == 403
    assert _FakeProxyService.saved is None


def test_proxy_admin_roundtrip_returns_no_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ai_router_module, "AiProxySettingsService", _FakeProxyService)
    monkeypatch.setattr(RBACService, "has_role", lambda self, *_a, **_k: True)

    saved = client.put(
        "/api/ai/proxy",
        json={"enabled": True, "url": "http://10.1.1.1:3128", "credential_id": 3},
    )

    assert saved.status_code == 200
    assert _FakeProxyService.saved is not None and _FakeProxyService.saved["actor"] == 1
    assert saved.json()["credential_name"] == "corp-proxy"
    assert "password" not in saved.text
    assert client.get("/api/ai/proxy").status_code == 200


def test_proxy_rejects_unknown_fields(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RBACService, "has_role", lambda self, *_a, **_k: True)
    response = client.put("/api/ai/proxy", json={"enabled": True, "password": "x"})
    assert response.status_code == 422


def test_general_context_gets_the_batfish_and_result_tools(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client)
    seen = _capture_chat(monkeypatch)

    body = {
        "messages": [{"role": "user", "content": "which route does 10.1.2.3 use on r1?"}],
        "context": {"surface": "general"},
    }
    response = client.post("/api/ai/chat", json=body)

    assert response.status_code == 200
    assert {"get_routes", "get_traceroute", "query_result", "fetch_slice"} <= set(seen["tools"])
    assert "propose_workflow" not in seen["tools"]
    assert "Data the user shares with you" in str(seen["system"])


@pytest.mark.parametrize("may_query", [True, False])
def test_general_batfish_tools_need_the_batfish_query_permission(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, may_query: bool
) -> None:
    _configure(client)
    seen = _capture_chat(monkeypatch)
    monkeypatch.setattr(
        RBACService,
        "has_permission",
        lambda self, _uid, resource, action: (
            (resource, action) != ("sources.batfish", "query") or may_query
        ),
    )

    response = client.post(
        "/api/ai/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "context": {"surface": "general"}},
    )

    assert response.status_code == 200
    assert ("get_routes" in seen["tools"]) is may_query


def test_general_context_rejects_extra_fields(client: TestClient) -> None:
    _configure(client)
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "context": {"surface": "general", "network": "x"},
    }

    assert client.post("/api/ai/chat", json=body).status_code == 422


# -- device commands (doc/AI_TOOL_CHAIN.md §29) -----------------------------------------------


def _device_result(**overrides):
    from services.ai_assistant.device_exec_service import DeviceCommandResult

    base = {
        "success": True,
        "error": None,
        "device_name": "LAB",
        "commands": ("show running-config",),
        "output": "$ show running-config\nhostname LAB",
        "truncated": False,
        "handle": "res_0123456789ab",
    }
    base.update(overrides)
    return DeviceCommandResult(**base)


class _FakeExecutor:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result, self.error, self.calls = result or _device_result(), error, []

    async def execute(self, *, user_id, token, credential_id, network_driver=None):
        self.calls.append((user_id, token, credential_id, network_driver))
        if self.error:
            raise self.error
        return self.result


def _register_domain_error_handler(client: TestClient) -> None:
    """The real app maps ``DomainError`` to its status; add the same before the first request."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from core.domain_exceptions import DomainError

    @client.app.exception_handler(DomainError)
    async def _handler(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@pytest.fixture
def device_client(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, dict]:
    monkeypatch.setattr(settings, "ai_device_commands_enabled", True)
    _register_domain_error_handler(client)
    _configure(client)
    client.patch("/api/ai/settings", json={"share_content_data": True})
    holder: dict = {"executor": _FakeExecutor()}
    client.app.dependency_overrides[ai_router_module.get_device_executor] = lambda: holder[
        "executor"
    ]
    return client, holder


_CONFIRM = {"token": "signed.token", "credential_id": 11}


def test_confirming_runs_the_executor_as_the_calling_user(device_client) -> None:
    client, holder = device_client

    response = client.post("/api/ai/exec/device-command", json=_CONFIRM)

    assert response.status_code == 200, response.text
    assert holder["executor"].calls == [(1, "signed.token", 11, None)]
    assert response.json() == {
        "success": True,
        "error": None,
        "device_name": "LAB",
        "commands": ["show running-config"],
        "output": "$ show running-config\nhostname LAB",
        "truncated": False,
        "handle": "res_0123456789ab",
    }


def test_the_users_device_type_choice_reaches_the_executor(device_client) -> None:
    client, holder = device_client

    response = client.post(
        "/api/ai/exec/device-command", json={**_CONFIRM, "network_driver": "cisco_xe"}
    )

    assert response.status_code == 200, response.text
    assert holder["executor"].calls == [(1, "signed.token", 11, "cisco_xe")]


def test_turning_content_sharing_off_stops_a_proposal_that_is_still_valid(device_client) -> None:
    client, holder = device_client
    client.patch("/api/ai/settings", json={"share_content_data": False})

    response = client.post("/api/ai/exec/device-command", json=_CONFIRM)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "content_sharing_off"
    assert holder["executor"].calls == []  # no SSH session, nothing stored


def test_the_assistant_must_be_set_up_to_confirm_a_run(device_client) -> None:
    client, holder = device_client
    client.patch("/api/ai/settings", json={"enabled": False})

    response = client.post("/api/ai/exec/device-command", json=_CONFIRM)

    assert response.status_code in (403, 409)
    assert holder["executor"].calls == []


def test_the_endpoint_does_not_exist_while_the_operator_switch_is_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ai_device_commands_enabled", False)
    holder = {"executor": _FakeExecutor()}
    client.app.dependency_overrides[ai_router_module.get_device_executor] = lambda: holder[
        "executor"
    ]

    assert client.post("/api/ai/exec/device-command", json=_CONFIRM).status_code == 404
    assert holder["executor"].calls == []


def test_the_endpoint_does_not_exist_while_the_assistant_is_off(
    device_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, holder = device_client
    monkeypatch.setattr(settings, "ai_assistant_enabled", False)

    assert client.post("/api/ai/exec/device-command", json=_CONFIRM).status_code == 404
    assert holder["executor"].calls == []


@pytest.mark.parametrize("missing", [("ai_assistant", "use"), ("netmiko", "execute")])
def test_both_permissions_are_required(
    device_client, monkeypatch: pytest.MonkeyPatch, missing: tuple[str, str]
) -> None:
    client, holder = device_client
    monkeypatch.setattr(
        RBACService,
        "has_permission",
        lambda self, _uid, resource, action: (resource, action) != missing,
    )

    assert client.post("/api/ai/exec/device-command", json=_CONFIRM).status_code == 403
    assert holder["executor"].calls == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"token": "t"},
        {"credential_id": 1},
        {"token": "", "credential_id": 1},
        {"token": "t", "credential_id": 0},
        {"token": "t", "credential_id": "x"},
        {"token": "x" * 5000, "credential_id": 1},
        {"token": "t", "credential_id": 1, "commands": ["show version"]},
        {"token": "t", "credential_id": 1, "host": "10.0.0.1"},
        {"token": "t", "credential_id": 1, "device": "LAB"},
        {"token": "t", "credential_id": 1, "network_driver": "rm -rf"},
        {"token": "t", "credential_id": 1, "network_driver": "cisco_ios_telnet"},
        {"token": "t", "credential_id": 1, "network_driver": ["cisco_ios"]},
    ],
)
def test_the_body_is_only_a_token_and_a_credential(device_client, body) -> None:
    client, holder = device_client

    assert client.post("/api/ai/exec/device-command", json=body).status_code == 422
    assert holder["executor"].calls == []


def test_the_endpoint_is_rate_limited() -> None:
    by_path = {r.path: r for r in router.routes if isinstance(r, APIRoute)}

    assert "rate_limited_ai-device-command" in _dependency_names(by_path["/ai/exec/device-command"])


def _errors():
    from services.ai_assistant.command_policy import CommandNotAllowedError
    from services.ai_assistant.device_access import (
        DeviceAccessDeniedError,
        DeviceAmbiguousError,
        DeviceNoAddressError,
        DeviceNotFoundError,
        DeviceUnsupportedPlatformError,
    )
    from services.ai_assistant.device_exec_service import (
        DeviceChangedError,
        InvalidConfirmationError,
        SecretsUnavailableError,
        TooManyRunsError,
    )

    return [
        (InvalidConfirmationError(), 400, "invalid_confirmation"),
        (CommandNotAllowedError("not allowed"), 400, "command_not_allowed"),
        (DeviceNotFoundError(), 404, "device_not_found"),
        (DeviceAmbiguousError(), 409, "device_ambiguous"),
        (DeviceNoAddressError(), 409, "device_no_address"),
        (DeviceUnsupportedPlatformError(), 409, "device_platform_unsupported"),
        (DeviceChangedError(), 409, "device_changed"),
        (DeviceAccessDeniedError(), 403, "device_access_denied"),
        (SecretsUnavailableError(), 503, "secrets_unavailable"),
        (TooManyRunsError(), 429, "too_many_runs"),
    ]


@pytest.mark.parametrize(("error", "status", "code"), _errors(), ids=lambda v: str(v)[:30])
def test_each_failure_has_its_own_status_and_code(device_client, error, status, code) -> None:
    client, holder = device_client
    holder["executor"] = _FakeExecutor(error=error)

    response = client.post("/api/ai/exec/device-command", json=_CONFIRM)

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    message = response.json()["detail"]["message"]
    assert message
    if code in {
        "command_not_allowed",
        "device_not_found",
        "device_ambiguous",
        "device_no_address",
        "device_platform_unsupported",
    }:
        assert message == str(error)  # the refusal reason / device problem is shown as it is


def test_an_unexpected_error_is_a_generic_500_without_internals(device_client) -> None:
    client, holder = device_client
    holder["executor"] = _FakeExecutor(error=RuntimeError("secret-internal-detail 10.9.9.9"))

    response = client.post("/api/ai/exec/device-command", json=_CONFIRM)

    assert response.status_code == 500
    assert "secret-internal-detail" not in response.text and "10.9.9.9" not in response.text


def test_a_domain_error_from_the_credential_lookup_keeps_its_status(device_client) -> None:
    from core.domain_exceptions import NotFoundError

    client, holder = device_client
    holder["executor"] = _FakeExecutor(error=NotFoundError("Credential 11 not found"))

    response = client.post("/api/ai/exec/device-command", json=_CONFIRM)

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("switch", "may_execute", "content", "expected"),
    [
        (True, True, True, True),
        (False, True, True, False),
        (True, False, True, False),
        (True, True, False, False),
    ],
)
def test_the_chat_offers_the_device_tool_only_when_all_three_gates_hold(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    switch: bool,
    may_execute: bool,
    content: bool,
    expected: bool,
) -> None:
    _configure(client)
    client.patch("/api/ai/settings", json={"share_content_data": content})
    monkeypatch.setattr(settings, "ai_device_commands_enabled", switch)
    monkeypatch.setattr(ai_router_module, "try_load_visible_secret_values", lambda _uid: [])
    monkeypatch.setattr(
        RBACService,
        "has_permission",
        lambda self, _uid, resource, action: (
            (resource, action) != ("netmiko", "execute") or may_execute
        ),
    )
    seen = _capture_chat(monkeypatch)

    client.post(
        "/api/ai/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "context": {"surface": "general"}},
    )

    assert ("propose_device_command" in seen["tools"]) is expected


@pytest.mark.parametrize(
    ("may_read", "content", "expected"),
    [(True, True, True), (False, True, False), (True, False, False)],
)
def test_the_chat_offers_config_backups_only_with_permission_and_content_opt_in(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    may_read: bool,
    content: bool,
    expected: bool,
) -> None:
    _configure(client)
    client.patch("/api/ai/settings", json={"share_content_data": content})
    monkeypatch.setattr(ai_router_module, "try_load_visible_secret_values", lambda _uid: [])
    monkeypatch.setattr(
        RBACService,
        "has_permission",
        lambda self, _uid, resource, action: (resource, action) != ("git.files", "read")
        or may_read,
    )
    seen = _capture_chat(monkeypatch)

    client.post(
        "/api/ai/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "context": {"surface": "general"}},
    )

    assert ("get_config_backup" in seen["tools"]) is expected
    assert ("list_config_backups" in seen["tools"]) is expected


def test_other_surfaces_never_get_the_device_tool(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(client)
    client.patch("/api/ai/settings", json={"share_content_data": True})
    monkeypatch.setattr(settings, "ai_device_commands_enabled", True)
    monkeypatch.setattr(ai_router_module, "try_load_visible_secret_values", lambda _uid: [])
    seen = _capture_chat(monkeypatch)

    client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "context": {"surface": "run_viewer", "run_id": 5},
        },
    )

    assert "propose_device_command" not in seen["tools"]


def test_the_device_type_choices_in_the_request_model_match_the_resolver_list() -> None:
    from typing import get_args

    from models.ai_assistant import DeviceDriver
    from services.ai_assistant.device_access import DEVICE_DRIVERS

    assert set(get_args(DeviceDriver)) == set(DEVICE_DRIVERS)
