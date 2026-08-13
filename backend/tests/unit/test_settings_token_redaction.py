"""SettingsService redacts Nautobot/Git tokens on read; blank PUT keeps the secret."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from models.settings import SettingCreate, SettingUpdate
from routers.sources.nautobot.ops import router as nautobot_source_ops_router
from services.auth.rbac_service import RBACService
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


GIT_VALUE = {
    "url": "https://git.example.com/org/repo.git",
    "credential_id": 99,
    "branch": "main",
    "verify_ssl": True,
}

NAUTOBOT_VALUE = {
    "url": "https://nautobot.example.com",
    "credential_id": 98,
    "verify_ssl": True,
}


class TestSettingsTokenRedaction:
    """Token/credential persistence only — URL policy is covered by
    test_source_connection_tests.py, so bypass URL validation here."""

    @pytest.fixture(autouse=True)
    def _bypass_url_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            SettingsService,
            "_validate_source_url",
            staticmethod(lambda source_type, value: value),
        )

    def test_list_redacts_nautobot_and_git_tokens(self) -> None:
        service = _service()
        nautobot = _setting("sources.nautobot.lab", dict(NAUTOBOT_VALUE))
        git = _setting("sources.git.lab", dict(GIT_VALUE), setting_id=2)
        other = _setting("app.misc", {"token": "keep-me"}, setting_id=3)
        service.repo.list_all.return_value = [nautobot, git, other]

        result = service.list_settings()

        by_key = {row.key: row.value for row in result.settings}
        assert by_key["sources.nautobot.lab"]["token"] == ""
        assert by_key["sources.nautobot.lab"]["token_configured"] is True
        assert "credential_id" not in by_key["sources.nautobot.lab"]
        assert by_key["sources.git.lab"]["token"] == ""
        assert by_key["sources.git.lab"]["token_configured"] is True
        assert "credential_id" not in by_key["sources.git.lab"]
        assert by_key["app.misc"]["token"] == "keep-me"
        assert "token_configured" not in by_key["app.misc"]
        assert nautobot.value["credential_id"] == 98
        assert git.value["credential_id"] == 99

    def test_get_redacts_token_and_sets_token_configured(self) -> None:
        service = _service()
        stored = _setting("sources.nautobot.lab", dict(NAUTOBOT_VALUE))
        service.repo.get_by_key.return_value = stored

        result = service.get_setting("sources.nautobot.lab")

        assert result.value["token"] == ""
        assert result.value["token_configured"] is True
        assert "credential_id" not in result.value
        assert stored.value["credential_id"] == 98

    def test_get_token_configured_false_when_blank(self) -> None:
        service = _service()
        service.repo.get_by_key.return_value = _setting(
            "sources.git.lab",
            {"url": "https://git.example.com/org/repo.git", "branch": "main", "verify_ssl": True},
        )

        result = service.get_setting("sources.git.lab")

        assert result.value["token"] == ""
        assert result.value["token_configured"] is False

    def test_create_git_source_persists_credential_id_not_token(self) -> None:
        service = _service()
        persisted: dict = {}
        service.repo.get_by_key.return_value = None
        service._credentials.create_credential.return_value = {"id": 99}

        def create(*, key: str, value: dict, description: str | None):
            persisted["key"] = key
            persisted["value"] = dict(value)
            return _setting(key, persisted["value"])

        service.repo.create.side_effect = create

        response = service.create_setting(
            SettingCreate(
                key="sources.git.lab",
                value={
                    "url": "https://git.example.com/org/repo.git",
                    "token": "git-secret",
                    "branch": "main",
                    "verify_ssl": True,
                },
            ),
        )

        assert response.value["token"] == ""
        assert response.value["token_configured"] is True
        assert "token" not in persisted["value"]
        assert persisted["value"]["credential_id"] == 99
        assert "token_configured" not in persisted["value"]
        service._credentials.create_credential.assert_called_once_with(
            name="git-lab",
            username="git-token",
            cred_type="generic",
            password="git-secret",
            source="git",
            visibility="global",
        )

        service.repo.get_by_key.return_value = _setting(
            "sources.git.lab",
            persisted["value"],
        )
        service._credentials.get_decrypted_password.return_value = "git-secret"
        config = service.get_source_config("git", "lab")
        assert config["token"] == "git-secret"
        assert "credential_id" not in config
        service._credentials.get_decrypted_password.assert_called_once_with(99)

    def test_create_git_source_without_token_is_rejected(self) -> None:
        service = _service()
        service.repo.get_by_key.return_value = None

        with pytest.raises(HTTPException):
            service.create_setting(
                SettingCreate(
                    key="sources.git.lab",
                    value={
                        "url": "https://git.example.com/org/repo.git",
                        "branch": "main",
                        "verify_ssl": True,
                    },
                ),
            )
        service._credentials.create_credential.assert_not_called()

    def test_create_nautobot_source_persists_credential_id_without_dns(self) -> None:
        service = _service()
        persisted: dict = {}
        service.repo.get_by_key.return_value = None
        service._credentials.create_credential.return_value = {"id": 98}

        def create(*, key: str, value: dict, description: str | None):
            persisted["value"] = dict(value)
            return _setting(key, persisted["value"])

        service.repo.create.side_effect = create

        response = service.create_setting(
            SettingCreate(
                key="sources.nautobot.lab",
                value={
                    "url": "https://nautobot.example.com",
                    "token": "nb-secret",
                    "verify_ssl": True,
                },
            ),
        )

        assert response.value["token"] == ""
        assert response.value["token_configured"] is True
        assert "token" not in persisted["value"]
        assert persisted["value"]["credential_id"] == 98

        service.repo.get_by_key.return_value = _setting(
            "sources.nautobot.lab",
            persisted["value"],
        )
        service._credentials.get_decrypted_password.return_value = "nb-secret"
        config = service.get_source_config("nautobot", "lab")
        assert config["token"] == "nb-secret"

    def test_update_blank_token_keeps_previous_secret(self) -> None:
        service = _service()
        existing = _setting("sources.git.lab", dict(GIT_VALUE))
        service.repo.get_by_key.return_value = existing
        persisted: dict = {}

        def update(setting, fields):
            persisted["value"] = dict(fields["value"])
            setting.value = persisted["value"]
            return setting

        service.repo.update.side_effect = update

        response = service.update_setting(
            "sources.git.lab",
            SettingUpdate(
                value={
                    "url": "https://git.example.com/org/repo.git",
                    "token": "",
                    "branch": "main",
                    "verify_ssl": True,
                },
            ),
        )

        assert persisted["value"]["credential_id"] == 99
        assert "token" not in persisted["value"]
        assert "token_configured" not in persisted["value"]
        assert response.value["token"] == ""
        assert response.value["token_configured"] is True
        service._credentials.update_credential.assert_not_called()
        service._credentials.create_credential.assert_not_called()

    def test_update_new_token_rotates_existing_credential(self) -> None:
        service = _service()
        existing = _setting("sources.git.lab", dict(GIT_VALUE))
        service.repo.get_by_key.return_value = existing
        persisted: dict = {}

        def update(setting, fields):
            persisted["value"] = dict(fields["value"])
            setting.value = persisted["value"]
            return setting

        service.repo.update.side_effect = update

        service.update_setting(
            "sources.git.lab",
            SettingUpdate(
                value={
                    "url": "https://git.example.com/org/repo.git",
                    "token": "new-secret",
                    "branch": "main",
                    "verify_ssl": True,
                },
            ),
        )

        service._credentials.update_credential.assert_called_once_with(99, password="new-secret")
        service._credentials.create_credential.assert_not_called()
        assert persisted["value"]["credential_id"] == 99
        assert "token" not in persisted["value"]

    def test_update_legacy_plaintext_row_migrates_to_credential(self) -> None:
        service = _service()
        existing = _setting(
            "sources.git.lab",
            {
                "url": "https://git.example.com/org/repo.git",
                "token": "legacy-secret",
                "branch": "main",
                "verify_ssl": True,
            },
        )
        service.repo.get_by_key.return_value = existing
        service._credentials.create_credential.return_value = {"id": 5}
        persisted: dict = {}

        def update(setting, fields):
            persisted["value"] = dict(fields["value"])
            setting.value = persisted["value"]
            return setting

        service.repo.update.side_effect = update

        service.update_setting(
            "sources.git.lab",
            SettingUpdate(
                value={
                    "url": "https://git.example.com/org/repo.git",
                    "token": "",
                    "branch": "main",
                    "verify_ssl": True,
                },
            ),
        )

        service._credentials.create_credential.assert_called_once_with(
            name="git-lab",
            username="git-token",
            cred_type="generic",
            password="legacy-secret",
            source="git",
            visibility="global",
        )
        assert persisted["value"]["credential_id"] == 5
        assert "token" not in persisted["value"]

    def test_delete_setting_deletes_linked_credential(self) -> None:
        service = _service()
        existing = _setting("sources.git.lab", dict(GIT_VALUE))
        service.repo.get_by_key.return_value = existing

        service.delete_setting("sources.git.lab")

        service.repo.delete.assert_called_once_with(existing)
        service._credentials.delete_credential.assert_called_once_with(99)


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
