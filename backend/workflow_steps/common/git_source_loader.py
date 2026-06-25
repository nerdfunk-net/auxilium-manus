"""Load git source settings for workflow export steps."""

from __future__ import annotations

from typing import Any

from core.database import get_db_session
from repositories.settings_repository import SettingsRepository
from services.settings.source_keys import build_source_key


def load_git_source_repository(git_source_id: str) -> dict[str, Any]:
    """Resolve a Settings git source into a GitService-compatible repository dict."""
    normalized_id = git_source_id.strip().lower()
    if not normalized_id:
        raise ValueError("store-artifact: git_source_id is not configured")

    setting_key = build_source_key("git", normalized_id)
    db = get_db_session()
    try:
        setting = SettingsRepository(db).get_by_key(setting_key)
    finally:
        db.close()

    if setting is None:
        raise ValueError(
            f"store-artifact: git source '{normalized_id}' not found in settings"
        )

    value = setting.value or {}
    url = str(value.get("url") or "").strip()
    if not url:
        raise ValueError(
            f"store-artifact: git source '{normalized_id}' has no URL configured"
        )

    on_disk_path = str(value.get("repository_path") or normalized_id).strip()
    if not on_disk_path:
        on_disk_path = normalized_id

    return {
        "id": normalized_id,
        "name": normalized_id,
        "url": url,
        "branch": str(value.get("branch") or "main").strip() or "main",
        "auth_type": "token",
        "token": str(value.get("token") or "").strip(),
        "username": str(value.get("username") or "").strip(),
        "path": on_disk_path.strip("/\\"),
        "verify_ssl": True,
        "git_author_name": value.get("git_author_name"),
        "git_author_email": value.get("git_author_email"),
        "is_active": True,
        "source_id": normalized_id,
    }
