"""AiSettingsService: per-user config, write-only key, master enable switch."""

from __future__ import annotations

import pytest
from _ai_helpers import FakeRepo
from pydantic import SecretStr

from core.crypto import EncryptionService
from models.ai_assistant import UserAiSettingsUpdate
from services.ai_assistant.exceptions import (
    AiAssistantDisabledError,
    AiAssistantNotConfiguredError,
    AiSettingsValidationError,
)
from services.ai_assistant.settings_service import DEFAULT_MODELS, AiSettingsService


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def service(repo: FakeRepo) -> AiSettingsService:
    return AiSettingsService(repo, EncryptionService("test-secret-key-for-ai-settings-00"))


def test_defaults_when_no_row_everything_is_off(service: AiSettingsService) -> None:
    result = service.get(1)

    assert result.enabled is False
    assert result.api_key_set is False
    assert result.share_inventory_data is False
    assert result.share_content_data is False
    assert result.provider == "anthropic"
    assert result.model == DEFAULT_MODELS["anthropic"]
    assert "anthropic" in result.available_providers


def test_api_key_is_encrypted_and_never_returned(
    service: AiSettingsService, repo: FakeRepo
) -> None:
    result = service.update(1, UserAiSettingsUpdate(api_key=SecretStr("sk-ant-secret-value")))

    assert result.api_key_set is True
    assert "sk-ant-secret-value" not in result.model_dump_json()
    stored = repo.rows[1].api_key_encrypted
    assert stored is not None and b"sk-ant-secret-value" not in stored


def test_omitted_key_leaves_existing_key_unchanged(service: AiSettingsService) -> None:
    service.update(1, UserAiSettingsUpdate(api_key=SecretStr("sk-ant-first")))
    service.update(1, UserAiSettingsUpdate(model="claude-sonnet-5-5"))

    assert service.get(1).api_key_set is True
    assert service.resolve_api_key(1) == "sk-ant-first"


def test_clear_api_key_removes_it(service: AiSettingsService) -> None:
    service.update(1, UserAiSettingsUpdate(api_key=SecretStr("sk-ant-first")))
    result = service.update(1, UserAiSettingsUpdate(clear_api_key=True))

    assert result.api_key_set is False
    assert service.resolve_api_key(1) is None


def test_api_key_and_clear_together_is_rejected(service: AiSettingsService) -> None:
    with pytest.raises(AiSettingsValidationError):
        service.update(1, UserAiSettingsUpdate(api_key=SecretStr("x"), clear_api_key=True))


def test_unknown_provider_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValueError):
        UserAiSettingsUpdate.model_validate({"provider": "nonsense"})


def test_settings_are_isolated_per_user(service: AiSettingsService) -> None:
    service.update(1, UserAiSettingsUpdate(api_key=SecretStr("sk-ant-user-one"), enabled=True))

    assert service.get(2).api_key_set is False
    assert service.resolve_api_key(2) is None


def test_data_sharing_flags_are_independent_and_default_off(service: AiSettingsService) -> None:
    result = service.update(1, UserAiSettingsUpdate(share_inventory_data=True))

    assert result.share_inventory_data is True
    assert result.share_content_data is False


def test_status_reasons(service: AiSettingsService) -> None:
    assert service.status(1, has_permission=False).reason == "no_permission"
    assert service.status(1, has_permission=True).reason == "disabled"

    service.update(1, UserAiSettingsUpdate(enabled=True))
    not_configured = service.status(1, has_permission=True)
    assert (not_configured.available, not_configured.reason) == (False, "not_configured")

    service.update(1, UserAiSettingsUpdate(api_key=SecretStr("sk-ant-k")))
    ok = service.status(1, has_permission=True)
    assert (ok.available, ok.reason) == (True, "ok")


def test_disabling_keeps_key_but_makes_assistant_unavailable(service: AiSettingsService) -> None:
    service.update(1, UserAiSettingsUpdate(enabled=True, api_key=SecretStr("sk-ant-k")))
    service.update(1, UserAiSettingsUpdate(enabled=False))

    assert service.get(1).api_key_set is True
    assert service.status(1, has_permission=True).available is False


def test_require_runtime_config_enforces_disabled_server_side(
    service: AiSettingsService,
) -> None:
    service.update(1, UserAiSettingsUpdate(api_key=SecretStr("sk-ant-k"), enabled=False))

    with pytest.raises(AiAssistantDisabledError):
        service.require_runtime_config(1)


def test_require_runtime_config_needs_a_key(service: AiSettingsService) -> None:
    service.update(1, UserAiSettingsUpdate(enabled=True))

    with pytest.raises(AiAssistantNotConfiguredError):
        service.require_runtime_config(1)


def test_runtime_config_hides_key_in_repr(service: AiSettingsService) -> None:
    service.update(1, UserAiSettingsUpdate(enabled=True, api_key=SecretStr("sk-ant-hidden")))

    config = service.require_runtime_config(1)

    assert config.api_key == "sk-ant-hidden"
    assert "sk-ant-hidden" not in repr(config)
    assert config.provider == "anthropic"
    assert config.model == DEFAULT_MODELS["anthropic"]


def test_undecryptable_key_is_reported_as_not_configured(
    service: AiSettingsService, repo: FakeRepo
) -> None:
    service.update(1, UserAiSettingsUpdate(enabled=True, api_key=SecretStr("sk-ant-k")))
    rotated = AiSettingsService(repo, EncryptionService("a-different-secret-key-0000000000"))

    with pytest.raises(AiAssistantNotConfiguredError):
        rotated.require_runtime_config(1)


def test_blank_model_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValueError):
        UserAiSettingsUpdate(model="   ")
    assert UserAiSettingsUpdate(model="  claude-haiku-5-5 ").model == "claude-haiku-5-5"


def test_default_model_is_haiku_and_both_claude_models_are_offered(
    service: AiSettingsService,
) -> None:
    result = service.get(1)

    assert result.model == "claude-haiku-5-5"
    assert DEFAULT_MODELS["anthropic"] == "claude-haiku-5-5"
    offered = [option.id for option in result.available_models["anthropic"]]
    assert offered == ["claude-haiku-5-5", "claude-sonnet-5-5"]


def test_sonnet_can_be_selected_and_is_used_at_runtime(service: AiSettingsService) -> None:
    service.update(1, UserAiSettingsUpdate(enabled=True, api_key=SecretStr("sk-ant-k")))
    service.update(1, UserAiSettingsUpdate(model="claude-sonnet-5-5"))

    assert service.get(1).model == "claude-sonnet-5-5"
    assert service.require_runtime_config(1).model == "claude-sonnet-5-5"


def test_a_model_that_is_not_offered_is_rejected(service: AiSettingsService) -> None:
    with pytest.raises(AiSettingsValidationError):
        service.update(1, UserAiSettingsUpdate(model="claude-opus-5-5"))


def test_a_stored_model_that_is_no_longer_offered_falls_back_to_the_default(
    service: AiSettingsService, repo: FakeRepo
) -> None:
    service.update(1, UserAiSettingsUpdate(enabled=True, api_key=SecretStr("sk-ant-k")))
    repo.rows[1].model = "claude-opus-5-5"

    assert service.get(1).model == "claude-haiku-5-5"
    assert service.require_runtime_config(1).model == "claude-haiku-5-5"


# -- phase 3: Gemini and OpenAI-compatible providers -------------------------------------


def test_gemini_is_selectable_with_its_own_default_model(service: AiSettingsService) -> None:
    result = service.update(1, UserAiSettingsUpdate(provider="gemini"))

    assert result.provider == "gemini"
    assert result.model == DEFAULT_MODELS["gemini"]
    assert [o.id for o in result.available_models["gemini"]][0] == DEFAULT_MODELS["gemini"]
    assert result.available_providers == ["anthropic", "gemini", "openai_compat"]


def test_changing_provider_resets_the_model_to_that_providers_default(
    service: AiSettingsService,
) -> None:
    service.update(1, UserAiSettingsUpdate(model="claude-sonnet-5-5"))

    result = service.update(1, UserAiSettingsUpdate(provider="gemini"))

    assert result.model == DEFAULT_MODELS["gemini"]


def test_a_claude_model_is_rejected_for_gemini(service: AiSettingsService) -> None:
    with pytest.raises(AiSettingsValidationError):
        service.update(1, UserAiSettingsUpdate(provider="gemini", model="claude-haiku-5-5"))


def test_openai_compat_takes_a_free_text_model_and_a_base_url(
    service: AiSettingsService,
) -> None:
    result = service.update(
        1,
        UserAiSettingsUpdate(
            provider="openai_compat", model="llama3.1:8b", base_url="http://10.0.0.5:11434/v1"
        ),
    )

    assert result.model == "llama3.1:8b"
    assert result.base_url == "http://10.0.0.5:11434/v1"
    assert result.available_models.get("openai_compat", []) == []


def test_openai_compat_is_configured_without_an_api_key(service: AiSettingsService) -> None:
    service.update(
        1,
        UserAiSettingsUpdate(
            enabled=True,
            provider="openai_compat",
            model="llama3.1:8b",
            base_url="http://10.0.0.5:11434/v1",
        ),
    )

    assert service.get(1).configured is True
    assert service.status(1, has_permission=True).available is True
    config = service.require_runtime_config(1)
    assert config.api_key == "" and config.base_url == "http://10.0.0.5:11434/v1"


def test_openai_compat_without_base_url_or_model_is_not_configured(
    service: AiSettingsService,
) -> None:
    service.update(1, UserAiSettingsUpdate(enabled=True, provider="openai_compat"))

    assert service.get(1).configured is False
    assert service.status(1, has_permission=True).reason == "not_configured"
    with pytest.raises(AiAssistantNotConfiguredError):
        service.require_runtime_config(1)


def test_base_url_is_only_accepted_for_openai_compat(service: AiSettingsService) -> None:
    with pytest.raises(AiSettingsValidationError):
        service.update(1, UserAiSettingsUpdate(base_url="http://10.0.0.5:11434/v1"))


def test_unsafe_base_urls_are_rejected_at_save_time(service: AiSettingsService) -> None:
    for url in (
        "http://169.254.169.254/v1",
        "ftp://10.0.0.5/v1",
        "http://user:pw@10.0.0.5/v1",
        "http://10.0.0.5:6379/x?y=",
        "http://10.0.0.5/admin#",
        "http://10.0.0.5/v1;p=1",
    ):
        with pytest.raises(AiSettingsValidationError):
            service.update(1, UserAiSettingsUpdate(provider="openai_compat", base_url=url))


def test_switching_away_from_openai_compat_clears_the_base_url(service: AiSettingsService) -> None:
    service.update(
        1,
        UserAiSettingsUpdate(
            provider="openai_compat", model="m", base_url="http://10.0.0.5:11434/v1"
        ),
    )

    result = service.update(1, UserAiSettingsUpdate(provider="anthropic"))

    assert result.base_url is None


def test_anthropic_and_gemini_still_need_a_key_to_be_configured(service: AiSettingsService) -> None:
    service.update(1, UserAiSettingsUpdate(enabled=True, provider="gemini"))
    assert service.get(1).configured is False

    service.update(1, UserAiSettingsUpdate(api_key=SecretStr("AIza-test-key")))
    assert service.get(1).configured is True


# -- one key per provider ------------------------------------------------------------------


def test_each_provider_keeps_its_own_key(service: AiSettingsService) -> None:
    service.update(1, UserAiSettingsUpdate(api_key=SecretStr("sk-ant-claude")))
    service.update(1, UserAiSettingsUpdate(provider="gemini", api_key=SecretStr("AIza-gemini")))

    assert service.resolve_api_key(1) == "AIza-gemini"
    service.update(1, UserAiSettingsUpdate(provider="anthropic"))
    assert service.resolve_api_key(1) == "sk-ant-claude"


def test_switching_to_a_provider_without_a_key_is_not_configured(
    service: AiSettingsService,
) -> None:
    service.update(1, UserAiSettingsUpdate(enabled=True, api_key=SecretStr("sk-ant-claude")))

    result = service.update(1, UserAiSettingsUpdate(provider="gemini"))

    assert result.api_key_set is False and result.configured is False
    assert service.status(1, has_permission=True).reason == "not_configured"
    with pytest.raises(AiAssistantNotConfiguredError):
        service.require_runtime_config(1)


def test_removing_a_key_only_affects_the_current_provider(service: AiSettingsService) -> None:
    service.update(1, UserAiSettingsUpdate(api_key=SecretStr("sk-ant-claude")))
    service.update(1, UserAiSettingsUpdate(provider="gemini", api_key=SecretStr("AIza-gemini")))

    service.update(1, UserAiSettingsUpdate(clear_api_key=True))
    assert service.get(1).api_key_set is False

    service.update(1, UserAiSettingsUpdate(provider="anthropic"))
    assert service.get(1).api_key_set is True
