from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models.user_ai_settings import UserAiSettings
from repositories.updates import apply_updates

_UPDATABLE_FIELDS = frozenset(
    {
        "enabled",
        "provider",
        "model",
        "base_url",
        "api_key_encrypted",
        "share_inventory_data",
        "share_content_data",
    }
)


class UserAiSettingsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_user_id(self, user_id: int) -> UserAiSettings | None:
        stmt = select(UserAiSettings).where(UserAiSettings.user_id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def upsert(self, user_id: int, values: Mapping[str, Any]) -> UserAiSettings:
        row = self.get_by_user_id(user_id)
        if row is None:
            row = UserAiSettings(user_id=user_id)
            self.db.add(row)
        apply_updates(row, values, _UPDATABLE_FIELDS)
        try:
            self.db.commit()
        except IntegrityError:
            # Two first-time saves raced on the unique user_id; the other one won, so
            # apply ours onto its row.
            self.db.rollback()
            existing = self.get_by_user_id(user_id)
            if existing is None:
                raise
            row = existing
            apply_updates(row, values, _UPDATABLE_FIELDS)
            self.db.commit()
        self.db.refresh(row)
        return row
