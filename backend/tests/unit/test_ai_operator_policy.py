"""Operator limits on the AI assistant (AI_ASSISTANT_ENABLED, AI_ALLOWED_PROVIDERS/_DATA)."""

from __future__ import annotations

import logging
import os
from unittest import mock

import pytest
from _ai_helpers import FakeRepo
from pydantic import SecretStr

from core import config
from core.crypto import EncryptionService
from core.production_guards import ai_policy_warnings, validate_ai_operator_policy
from models.ai_assistant import UserAiSettingsUpdate
from services.ai_assistant.exceptions import AiAssistantDisabledError, AiSettingsValidationError
from services.ai_assistant.policy import effective_share
from services.ai_assistant.settings_service import AiSettingsService

ALL_DATA = frozenset(
    {"inventory", "addresses", "custom_fields", "config_context", "content", "report"}
)


@pytest.fixture
def service() -> AiSettingsService:
    return AiSettingsService(FakeRepo(), EncryptionService("test-secret-key-for-ai-operator-0"))


def _configure(service: AiSettingsService, **extra: object) -> None:
    service.update(
        1,
        UserAiSettingsUpdate(
            enabled=True, provider="anthropic", api_key=SecretStr("sk-ant-x"), **extra
        ),
    )


def test_assistant_off_by_default() -> None:
    unset = ("AI_ASSISTANT_ENABLED", "AI_ALLOWED_PROVIDERS", "AI_ALLOWED_DATA")
    with mock.patch.dict("os.environ"):
        for name in unset:
            os.environ.pop(name, None)
        built = config.Settings()
    assert built.ai_assistant_enabled is False
    assert built.ai_allowed_providers == frozenset()
    assert built.ai_allowed_data == frozenset()


def test_operator_switch_off_refuses_every_runtime_config(
    service: AiSettingsService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(service)
    monkeypatch.setattr(config.settings, "ai_assistant_enabled", False)

    with pytest.raises(AiAssistantDisabledError, match="administrator"):
        service.require_runtime_config(1)
    with pytest.raises(AiAssistantDisabledError, match="administrator"):
        service.require_runtime_config(1, require_enabled=False)
    assert service.status(1, has_permission=True).reason == "operator_disabled"


def test_disallowed_provider_refused(
    service: AiSettingsService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(service)
    monkeypatch.setattr(config.settings, "ai_allowed_providers", frozenset({"gemini"}))

    with pytest.raises(AiAssistantDisabledError, match="provider"):
        service.require_runtime_config(1)
    assert service.status(1, has_permission=True).reason == "provider_not_allowed"
    with pytest.raises(AiSettingsValidationError, match="not allowed"):
        service.update(1, UserAiSettingsUpdate(provider="anthropic"))


def test_user_share_is_anded_with_operator_set(
    service: AiSettingsService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(service, share_content_data=True, share_inventory_data=True)
    monkeypatch.setattr(config.settings, "ai_allowed_data", ALL_DATA - {"content"})

    runtime = service.require_runtime_config(1)

    assert runtime.share_content_data is False
    assert runtime.share_inventory_data is True
    assert runtime.sharing.content is False
    # The stored choice is untouched: it applies again once the operator allows content.
    assert service.get(1).share_content_data is True


def test_operator_limits_are_exposed_to_the_settings_page(
    service: AiSettingsService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config.settings, "ai_allowed_data", frozenset({"inventory"}))

    view = service.get(1)

    assert view.operator_enabled is True
    assert view.operator_data == ["inventory"]
    assert view.operator_providers == sorted(config.settings.ai_allowed_providers)


def test_effective_share_needs_both() -> None:
    assert effective_share("share_report_data", True, {"report"}) is True
    assert effective_share("share_report_data", True, set()) is False
    assert effective_share("share_report_data", False, {"report"}) is False


@pytest.mark.parametrize(
    ("providers", "data"),
    [({"openai"}, set()), (set(), {"everything"})],
)
def test_unknown_token_refuses_to_start(providers: set[str], data: set[str]) -> None:
    with pytest.raises(RuntimeError, match="AI_ALLOWED"):
        validate_ai_operator_policy(providers=frozenset(providers), data=frozenset(data))
    env = {"AI_ALLOWED_PROVIDERS": ",".join(providers), "AI_ALLOWED_DATA": ",".join(data)}
    with mock.patch.dict("os.environ", env, clear=False), pytest.raises(RuntimeError):
        config.Settings()


def test_set_while_disabled_warns() -> None:
    warning = ai_policy_warnings(enabled=False, providers=frozenset({"gemini"}), data=frozenset())
    assert warning and "AI_ASSISTANT_ENABLED" in warning[0]
    assert ai_policy_warnings(enabled=True, providers=frozenset({"gemini"}), data=frozenset()) == []
    assert ai_policy_warnings(enabled=False, providers=frozenset(), data=frozenset()) == []


def test_update_logs_field_names_not_values(
    service: AiSettingsService, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="services.ai_assistant.settings_service"):
        _configure(service, share_content_data=True)

    text = " ".join(record.getMessage() for record in caplog.records)
    assert "ai_settings_changed user_id=1" in text
    assert "api_key_set" in text and "share_content_data" in text
    assert "sk-ant-x" not in text
