"""Load git source settings for workflow export steps."""

from __future__ import annotations

from typing import Any

from core.database import get_db_session
from services.settings.exceptions import SourceConfigError
from services.settings.settings_service import SettingsService
from services.sources.git.git_source_service import source_config_to_git_repository


def load_git_source_repository(git_source_id: str) -> dict[str, Any]:
    """Resolve a Settings git source into a GitService-compatible repository dict.

    Goes through ``SettingsService.get_source_config_for_step`` (not a raw settings
    lookup) so a source whose secret is stored as ``credential_id`` — the normal case
    for sources created through the Settings UI — is decrypted into a usable token.
    """
    normalized_id = git_source_id.strip().lower()
    if not normalized_id:
        raise ValueError("store-artifact: git_source_id is not configured")

    db = get_db_session()
    try:
        try:
            source_config = SettingsService(db).get_source_config_for_step("git", normalized_id)
        except SourceConfigError as exc:
            raise ValueError(f"store-artifact: {exc}") from exc
    finally:
        db.close()

    if not str(source_config.get("url") or "").strip():
        raise ValueError(f"store-artifact: git source '{normalized_id}' has no URL configured")

    repository = source_config_to_git_repository(source_config)
    repository["git_author_name"] = source_config.get("git_author_name")
    repository["git_author_email"] = source_config.get("git_author_email")
    repository["is_active"] = True
    return repository
