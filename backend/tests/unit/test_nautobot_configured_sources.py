"""``GET /sources/nautobot/configured-sources``: the source id, URL and readiness for a user with
``sources.nautobot:read`` who holds no ``settings:read`` (the ``viewer`` role)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from models.sources_nautobot import NautobotConfiguredSource, NautobotConfiguredSourcesResponse
from routers.sources.nautobot.ops import router as ops_router
from services.auth.rbac_service import RBACService
from services.settings.settings_service import SettingsService


def _row(key: str, value: object) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=1, key=key, value=value, description=None, created_at=now, updated_at=now
    )


def _service(rows: list[SimpleNamespace]) -> SettingsService:
    service = SettingsService(MagicMock())
    service.repo = MagicMock()
    service.repo.list_all.return_value = rows
    return service


def _dump(service: SettingsService) -> list[dict]:
    return [source.model_dump() for source in service.list_nautobot_source_summaries().sources]


class TestListNautobotSourceSummaries:
    def test_asks_for_the_nautobot_prefix_only(self) -> None:
        service = _service([])
        service.list_nautobot_source_summaries()
        service.repo.list_all.assert_called_once_with(key_prefix="sources.nautobot.")

    def test_reports_id_url_and_readiness(self) -> None:
        service = _service(
            [
                _row("sources.nautobot.lab", {"url": "https://nb.example", "credential_id": 4}),
                _row("sources.nautobot.dev", {"url": "https://dev.example"}),
            ]
        )
        assert _dump(service) == [
            {"source_id": "lab", "url": "https://nb.example", "token_configured": True},
            {"source_id": "dev", "url": "https://dev.example", "token_configured": False},
        ]

    def test_leaves_every_other_field_out(self) -> None:
        service = _service(
            [
                _row(
                    "sources.nautobot.lab",
                    {
                        "url": "https://nb.example",
                        "credential_id": 4,
                        "token": "s3cret",
                        "verify_ssl": False,
                        "timeout": 30,
                    },
                )
            ]
        )
        (summary,) = _dump(service)
        assert set(summary) == {"source_id", "url", "token_configured"}
        assert "s3cret" not in repr(summary)

    @pytest.mark.parametrize("value", [None, [], "text", 3, {}, {"url": ""}, {"url": 5}])
    def test_a_row_without_a_usable_url_is_left_out(self, value: object) -> None:
        # The settings parser always dropped such rows; one of them must not shadow a usable source.
        service = _service(
            [
                _row("sources.nautobot.aaa", value),
                _row("sources.nautobot.bbb", {"url": "https://nb.example", "credential_id": 1}),
            ]
        )
        assert [s["source_id"] for s in _dump(service)] == ["bbb"]

    def test_skips_keys_that_are_not_valid_source_ids(self) -> None:
        service = _service(
            [
                _row("sources.nautobot.", {"url": "x"}),
                _row("sources.nautobot.Bad Id", {"url": "x"}),
                _row("sources.nautobot.ok", {"url": "y"}),
            ]
        )
        assert [s["source_id"] for s in _dump(service)] == ["ok"]


@pytest.fixture
def client(monkeypatch):
    granted: set[tuple[str, str]] = {("sources.nautobot", "read")}
    monkeypatch.setattr(
        RBACService,
        "has_permission",
        lambda self, _user_id, resource, action: (resource, action) in granted,
    )
    rows = [_row("sources.nautobot.lab", {"url": "https://nb.example", "credential_id": 9})]
    monkeypatch.setattr(SettingsService, "__init__", lambda self, db: None)
    monkeypatch.setattr(
        SettingsService,
        "list_nautobot_source_summaries",
        lambda self: NautobotConfiguredSourcesResponse(
            sources=[
                NautobotConfiguredSource(
                    source_id="lab", url=rows[0].value["url"], token_configured=True
                )
            ]
        ),
    )
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    user = User(username="viewer", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client, granted


def test_a_user_with_only_sources_nautobot_read_gets_the_sources(client) -> None:
    test_client, _granted = client
    response = test_client.get("/api/sources/nautobot/configured-sources")
    assert response.status_code == 200
    assert response.json() == {
        "sources": [{"source_id": "lab", "url": "https://nb.example", "token_configured": True}]
    }


def test_settings_read_is_not_needed(client) -> None:
    test_client, granted = client
    assert ("settings", "read") not in granted
    assert test_client.get("/api/sources/nautobot/configured-sources").status_code == 200


def test_a_user_without_sources_nautobot_read_is_refused(client) -> None:
    test_client, granted = client
    granted.clear()
    assert test_client.get("/api/sources/nautobot/configured-sources").status_code == 403


def test_the_static_path_is_registered_before_the_inventory_id_route() -> None:
    """``GET /{inventory_id}`` is an int path; if it came first this path would be a 422."""
    import main

    paths = list(main.app.openapi()["paths"])
    configured = paths.index("/api/sources/nautobot/configured-sources")
    by_id = paths.index("/api/sources/nautobot/{inventory_id}")
    assert configured < by_id
