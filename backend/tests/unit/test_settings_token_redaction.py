"""SettingsService redacts Nautobot tokens on read; blank PUT keeps the secret."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.domain_exceptions import ValidationFailedError
from core.models.users import User
from models.settings import SettingCreate, SettingUpdate
from routers.sources.nautobot.ops import router as nautobot_source_ops_router
from services.auth.rbac_service import RBACService
from services.credentials.source_credentials import SourceCredentialError
from services.settings.settings_service import SettingsService


def _setting(key: str, value: dict, setting_id: int = 1) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=setting_id,
        key=key,
        value=value,
        description=None,
        created_at=now,
        updated_at=now,
    )


def _service() -> SettingsService:
    service = SettingsService(MagicMock())
    service.repo = MagicMock()
    service._credentials = MagicMock()
    return service


NAUTOBOT_VALUE = {
    "url": "https://nautobot.example.com",
    "credential_id": 98,
    "verify_ssl": True,
}


class TestSettingsTokenRedaction:
    """credential_id persistence only — URL policy is covered by
    test_source_connection_tests.py, so bypass URL validation here."""

    @pytest.fixture(autouse=True)
    def _bypass_url_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            SettingsService,
            "_validate_source_url",
            staticmethod(lambda source_type, value: value),
        )

    @pytest.fixture(autouse=True)
    def _stub_global_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.global_calls: list[int] = []

        def _assert(db, credential_id):  # noqa: ANN001
            self.global_calls.append(credential_id)
            return {"id": credential_id, "name": "vault", "visibility": "global"}

        monkeypatch.setattr("services.settings.settings_service.assert_global_credential", _assert)

    def _service_with_name(self) -> SettingsService:
        service = _service()
        service._credentials.get_credential_by_id.return_value = {"id": 98, "name": "vault"}
        return service

    def test_list_exposes_credential_id_and_name(self) -> None:
        service = self._service_with_name()
        nautobot = _setting("sources.nautobot.lab", dict(NAUTOBOT_VALUE))
        other = _setting("app.misc", {"token": "keep-me"}, setting_id=3)
        service.repo.list_all.return_value = [nautobot, other]

        result = service.list_settings()

        by_key = {row.key: row.value for row in result.settings}
        assert by_key["sources.nautobot.lab"]["token"] == ""
        assert by_key["sources.nautobot.lab"]["token_configured"] is True
        assert by_key["sources.nautobot.lab"]["credential_id"] == 98
        assert by_key["sources.nautobot.lab"]["credential_name"] == "vault"
        assert by_key["app.misc"]["token"] == "keep-me"
        assert "token_configured" not in by_key["app.misc"]

    def test_get_exposes_credential_id(self) -> None:
        service = self._service_with_name()
        stored = _setting("sources.nautobot.lab", dict(NAUTOBOT_VALUE))
        service.repo.get_by_key.return_value = stored

        result = service.get_setting("sources.nautobot.lab")

        assert result.value["token"] == ""
        assert result.value["token_configured"] is True
        assert result.value["credential_id"] == 98

    def test_create_requires_credential_id(self) -> None:
        service = _service()
        service.repo.get_by_key.return_value = None
        with pytest.raises(ValidationFailedError):
            service.create_setting(
                SettingCreate(
                    key="sources.nautobot.lab",
                    value={"url": "https://nautobot.example.com", "verify_ssl": True},
                ),
            )

    def test_create_persists_credential_id(self) -> None:
        service = _service()
        persisted: dict = {}
        service.repo.get_by_key.return_value = None

        def create(*, key: str, value: dict, description: str | None):
            persisted["value"] = dict(value)
            return _setting(key, persisted["value"])

        service.repo.create.side_effect = create

        response = service.create_setting(
            SettingCreate(
                key="sources.nautobot.lab",
                value={
                    "url": "https://nautobot.example.com",
                    "credential_id": 98,
                    "verify_ssl": True,
                },
            ),
        )

        assert self.global_calls == [98]
        assert response.value["token"] == ""
        assert response.value["token_configured"] is True
        assert "token" not in persisted["value"]
        assert persisted["value"]["credential_id"] == 98

        service.repo.get_by_key.return_value = _setting("sources.nautobot.lab", persisted["value"])
        service._credentials.get_decrypted_password.return_value = "nb-secret"
        config = service.get_source_config("nautobot", "lab")
        assert config["token"] == "nb-secret"

    def test_create_rejects_non_global_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = _service()
        service.repo.get_by_key.return_value = None

        def _boom(db, credential_id):  # noqa: ANN001
            raise SourceCredentialError("must be global")

        monkeypatch.setattr("services.settings.settings_service.assert_global_credential", _boom)
        with pytest.raises(ValidationFailedError):
            service.create_setting(
                SettingCreate(
                    key="sources.nautobot.lab",
                    value={
                        "url": "https://nautobot.example.com",
                        "credential_id": 5,
                        "verify_ssl": True,
                    },
                ),
            )

    def test_update_without_credential_id_keeps_existing(self) -> None:
        service = _service()
        existing = _setting("sources.nautobot.lab", dict(NAUTOBOT_VALUE))
        service.repo.get_by_key.return_value = existing
        persisted: dict = {}

        def update(setting, fields):
            persisted["value"] = dict(fields["value"])
            setting.value = persisted["value"]
            return setting

        service.repo.update.side_effect = update

        service.update_setting(
            "sources.nautobot.lab",
            SettingUpdate(value={"url": "https://nautobot.example.com", "verify_ssl": True}),
        )

        assert persisted["value"]["credential_id"] == 98
        assert "token" not in persisted["value"]
        assert self.global_calls == []

    def test_update_with_new_credential_id_relinks(self) -> None:
        service = _service()
        existing = _setting("sources.nautobot.lab", dict(NAUTOBOT_VALUE))
        service.repo.get_by_key.return_value = existing
        persisted: dict = {}

        def update(setting, fields):
            persisted["value"] = dict(fields["value"])
            setting.value = persisted["value"]
            return setting

        service.repo.update.side_effect = update

        service.update_setting(
            "sources.nautobot.lab",
            SettingUpdate(
                value={
                    "url": "https://nautobot.example.com",
                    "credential_id": 55,
                    "verify_ssl": True,
                },
            ),
        )

        assert self.global_calls == [55]
        assert persisted["value"]["credential_id"] == 55

    def test_delete_setting_does_not_touch_credential(self) -> None:
        service = _service()
        existing = _setting("sources.nautobot.lab", dict(NAUTOBOT_VALUE))
        service.repo.get_by_key.return_value = existing

        service.delete_setting("sources.nautobot.lab")

        service.repo.delete.assert_called_once_with(existing)
        service._credentials.delete_credential.assert_not_called()


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def nautobot_ops_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(nautobot_source_ops_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db
    return app


def test_custom_fields_without_source_id_returns_422(nautobot_ops_app: FastAPI) -> None:
    with TestClient(nautobot_ops_app) as client:
        response = client.get("/api/sources/nautobot/custom-fields")
    assert response.status_code == 422


def test_custom_fields_uses_source_id_not_nautobot_token(
    nautobot_ops_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "dependencies.SettingsService.get_source_config",
        lambda self, source_type, source_id: {
            "url": "https://nautobot.example.com",
            "token": "stored-secret",
            "verify_ssl": True,
            "source_id": source_id,
        },
    )
    mock_source = MagicMock()
    mock_source.get_custom_fields = AsyncMock(return_value=[{"name": "site"}])
    monkeypatch.setattr(
        "routers.sources.nautobot.ops._build_source_service",
        lambda *_a, **_k: mock_source,
    )

    with TestClient(nautobot_ops_app) as client:
        response = client.get(
            "/api/sources/nautobot/custom-fields",
            params={"source_id": "lab"},
        )

    assert response.status_code == 200
    assert response.json() == {"custom_fields": [{"name": "site"}]}
    assert "nautobot_token" not in str(response.request.url)
    mock_source.get_custom_fields.assert_awaited_once()
