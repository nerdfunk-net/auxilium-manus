"""Global AI proxy settings: validation, credential binding, resolve, generic-API guard."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.domain_exceptions import NotFoundError, ValidationFailedError
from core.models.credentials import Credential
from core.models.git import GitRepository
from core.models.secret_manager import SecretManagerConnection
from core.models.settings import Setting
from core.models.templates import Template
from core.models.users import User
from core.models.workflows import Workflow
from models.ai_assistant import AiProxySettingsUpdate
from models.settings import SettingCreate, SettingUpdate
from repositories.credential_usage_repository import CredentialUsageRepository
from services.ai_assistant.exceptions import (
    AiAssistantNotConfiguredError,
    AiSettingsValidationError,
)
from services.ai_assistant.proxy_key import AI_PROXY_SETTINGS_KEY
from services.ai_assistant.proxy_settings_service import AiProxySettingsService
from services.credentials.credentials_service import CredentialsService
from services.credentials.usage import find_dependants
from services.settings.settings_service import SettingsService

PROXY_URL = "http://10.1.1.1:3128"


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Credential.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Credential.__table__,
            Setting.__table__,
            GitRepository.__table__,
            SecretManagerConnection.__table__,
            Template.__table__,
            Workflow.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, username="owner", email="o@x.y", password_hash="x"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    # The proxy host is a literal IP; keep the policy from resolving anything.
    monkeypatch.setattr("core.safe_urls._assert_resolved_hosts_allowed", lambda host: None)


@pytest.fixture(autouse=True)
def _password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CredentialsService, "get_decrypted_password", lambda self, cid: "s3cret-pw")


def _credential(db: Session, *, kind: str = "generic", visibility: str = "global") -> Credential:
    row = Credential(
        name="corp-proxy", username="svc-proxy", type=kind, visibility=visibility, owner_user_id=1
    )
    db.add(row)
    db.commit()
    return row


def test_defaults_are_off(db: Session) -> None:
    result = AiProxySettingsService(db).get()
    assert (result.enabled, result.configured, result.url) == (False, False, "")
    assert AiProxySettingsService(db).resolve() is None


def test_save_and_resolve_with_basic_auth_credential(db: Session) -> None:
    cred = _credential(db)
    service = AiProxySettingsService(db)

    saved = service.update(
        AiProxySettingsUpdate(
            enabled=True,
            url=PROXY_URL,
            credential_id=cred.id,
            bypass_hosts=["Ollama.Corp", "ollama.corp"],
        )
    )

    assert saved.configured and saved.credential_name == "corp-proxy"
    assert saved.bypass_hosts == ["ollama.corp"]
    assert "s3cret-pw" not in saved.model_dump_json()
    resolved = service.resolve()
    assert resolved is not None
    assert (resolved.url, resolved.username, resolved.password) == (
        PROXY_URL,
        "svc-proxy",
        "s3cret-pw",
    )
    assert resolved.bypass_hosts == ("ollama.corp",)
    assert "s3cret-pw" not in repr(resolved)


def test_proxy_without_credential_resolves_without_auth(db: Session) -> None:
    service = AiProxySettingsService(db)
    service.update(AiProxySettingsUpdate(enabled=True, url=PROXY_URL))
    resolved = service.resolve()
    assert resolved is not None and resolved.username is None


def test_disabled_proxy_resolves_to_none_but_keeps_values(db: Session) -> None:
    service = AiProxySettingsService(db)
    service.update(AiProxySettingsUpdate(enabled=False, url=PROXY_URL))
    assert service.resolve() is None
    assert service.get().url == PROXY_URL


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://10.1.1.1",
        "http://user:pw@10.1.1.1:3128",
        "http://10.1.1.1:3128?x=1",
        "http://169.254.169.254",
    ],
)
def test_enabled_rejects_bad_urls(db: Session, url: str) -> None:
    with pytest.raises(AiSettingsValidationError):
        AiProxySettingsService(db).update(AiProxySettingsUpdate(enabled=True, url=url))


@pytest.mark.parametrize(
    ("kind", "visibility"), [("ssh", "global"), ("generic", "private"), ("token", "global")]
)
def test_rejects_wrong_type_or_private_credential(db: Session, kind: str, visibility: str) -> None:
    cred = _credential(db, kind=kind, visibility=visibility)
    with pytest.raises(AiSettingsValidationError):
        AiProxySettingsService(db).update(
            AiProxySettingsUpdate(enabled=True, url=PROXY_URL, credential_id=cred.id)
        )


def test_rejects_missing_credential(db: Session) -> None:
    with pytest.raises(AiSettingsValidationError):
        AiProxySettingsService(db).update(
            AiProxySettingsUpdate(enabled=True, url=PROXY_URL, credential_id=999)
        )


def test_resolve_fails_closed_when_credential_vanished(db: Session) -> None:
    cred = _credential(db)
    service = AiProxySettingsService(db)
    service.update(AiProxySettingsUpdate(enabled=True, url=PROXY_URL, credential_id=cred.id))
    db.delete(cred)
    db.commit()

    with pytest.raises(AiAssistantNotConfiguredError) as caught:
        service.resolve()
    assert "corp-proxy" not in str(caught.value)


def test_update_replaces_existing_row(db: Session) -> None:
    service = AiProxySettingsService(db)
    service.update(AiProxySettingsUpdate(enabled=True, url=PROXY_URL))
    service.update(AiProxySettingsUpdate(enabled=False, url="http://10.2.2.2:8080"))
    assert db.query(Setting).filter_by(key=AI_PROXY_SETTINGS_KEY).count() == 1
    assert service.get().url == "http://10.2.2.2:8080"


def test_model_forbids_unknown_fields_and_bad_hosts() -> None:
    with pytest.raises(ValueError):
        AiProxySettingsUpdate(enabled=True, url=PROXY_URL, password="x")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        AiProxySettingsUpdate(enabled=True, url=PROXY_URL, bypass_hosts=["a b"])


def test_generic_settings_api_cannot_touch_the_proxy_row(db: Session) -> None:
    service = SettingsService(db)
    with pytest.raises(ValidationFailedError):
        service.create_setting(SettingCreate(key=AI_PROXY_SETTINGS_KEY, value={"enabled": True}))
    AiProxySettingsService(db).update(AiProxySettingsUpdate(enabled=True, url=PROXY_URL))
    with pytest.raises(ValidationFailedError):
        service.update_setting(AI_PROXY_SETTINGS_KEY, SettingUpdate(value={"url": "http://evil:1"}))
    with pytest.raises(ValidationFailedError):
        service.delete_setting(AI_PROXY_SETTINGS_KEY)
    assert AiProxySettingsService(db).get().url == PROXY_URL


def test_credential_in_use_by_proxy_is_a_dependant(db: Session) -> None:
    cred = _credential(db)
    AiProxySettingsService(db).update(
        AiProxySettingsUpdate(enabled=True, url=PROXY_URL, credential_id=cred.id)
    )
    kinds = [d.kind for d in find_dependants(_usage_repo(db), cred)]
    assert "ai_proxy" in kinds


def _usage_repo(db: Session) -> CredentialUsageRepository:
    return CredentialUsageRepository(db)


@pytest.mark.parametrize("entry", ["*.com", "1", "0.0.0.0/0", "2.3"])
def test_update_refuses_bypass_entries_that_exempt_too_much(db: Session, entry: str) -> None:
    with pytest.raises(AiSettingsValidationError):
        AiProxySettingsService(db).update(
            AiProxySettingsUpdate(enabled=True, url=PROXY_URL, bypass_hosts=[entry])
        )


def test_generic_settings_reads_hide_the_proxy_row(db: Session) -> None:
    AiProxySettingsService(db).update(
        AiProxySettingsUpdate(enabled=True, url=PROXY_URL, bypass_hosts=["lan.corp"])
    )
    db.add(Setting(key="ai_other", value={"x": 1}))
    db.commit()
    service = SettingsService(db)

    listed = [s.key for s in service.list_settings().settings]
    prefixed = [s.key for s in service.list_settings(key_prefix="ai_").settings]

    assert AI_PROXY_SETTINGS_KEY not in listed and AI_PROXY_SETTINGS_KEY not in prefixed
    assert "ai_other" in listed
    with pytest.raises(NotFoundError):
        service.get_setting(AI_PROXY_SETTINGS_KEY)


def test_boolean_credential_id_is_not_credential_one(db: Session) -> None:
    cred = _credential(db)
    assert cred.id == 1
    db.add(Setting(key=AI_PROXY_SETTINGS_KEY, value={"enabled": True, "credential_id": True}))
    db.commit()

    assert "ai_proxy" not in [d.kind for d in find_dependants(_usage_repo(db), cred)]


def test_change_is_logged_with_the_actor_but_not_the_url(
    db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    AiProxySettingsService(db).update(
        AiProxySettingsUpdate(enabled=True, url=PROXY_URL), actor_user_id=42
    )
    line = next(r.getMessage() for r in caplog.records if "ai_proxy_changed" in r.getMessage())
    assert "actor_user_id=42" in line
    assert "10.1.1.1" not in line
