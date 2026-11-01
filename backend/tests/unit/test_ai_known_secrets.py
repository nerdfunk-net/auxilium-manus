"""Credential values for exact-match redaction: a failed lookup must not fail open."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from models.ai_assistant import GeneralContext
from services.ai_assistant import known_secrets
from services.ai_assistant.settings_service import AiRuntimeConfig

MOD = "services.ai_assistant.known_secrets"


def _config() -> AiRuntimeConfig:
    return AiRuntimeConfig(
        provider="anthropic",
        model="claude-haiku-5-5",
        base_url=None,
        api_key="sk-ant-test",
        share_inventory_data=True,
        share_device_addresses=True,
        share_content_data=True,
    )


def test_a_failed_lookup_is_reported_as_none_not_as_an_empty_list() -> None:
    with patch(f"{MOD}.SessionLocal", side_effect=RuntimeError("db down")):
        assert known_secrets.try_load_visible_secret_values(7) is None


def test_a_successful_lookup_returns_the_values() -> None:
    service = MagicMock()
    service.return_value.visible_secret_values.return_value = ["s3cretvalue1"]
    with patch(f"{MOD}.SessionLocal", MagicMock()), patch(f"{MOD}.CredentialsService", service):
        assert known_secrets.try_load_visible_secret_values(7) == ["s3cretvalue1"]


def test_the_old_helper_still_never_raises() -> None:
    with patch(f"{MOD}.SessionLocal", side_effect=RuntimeError("db down")):
        assert known_secrets.load_visible_secret_values(7) == []


def test_content_is_withheld_for_the_request_when_the_secrets_cannot_be_loaded() -> None:
    from routers import ai_assistant as router

    user = MagicMock()
    user.id = 7
    with patch.object(router, "try_load_visible_secret_values", return_value=None):
        session = router._session_for(
            GeneralContext(surface="general"), user, MagicMock(), _config(), can_query_batfish=True
        )

    assert "run and device content" not in session.system
    assert "addresses" in session.system  # the other opt-ins are untouched


def test_content_stays_shared_when_the_secrets_were_loaded() -> None:
    from routers import ai_assistant as router

    user = MagicMock()
    user.id = 7
    with patch.object(router, "try_load_visible_secret_values", return_value=["s3cretvalue1"]):
        session = router._session_for(
            GeneralContext(surface="general"), user, MagicMock(), _config(), can_query_batfish=True
        )

    assert "run and device content" in session.system
