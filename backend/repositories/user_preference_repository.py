from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.user_preferences import UserPreference


class UserPreferenceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_user_id(self, user_id: int) -> UserPreference | None:
        stmt = select(UserPreference).where(UserPreference.user_id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def upsert_dashboard_layout(self, user_id: int, layout: dict[str, Any]) -> UserPreference:
        preference = self.get_by_user_id(user_id)
        if preference is None:
            preference = UserPreference(user_id=user_id)
            self.db.add(preference)

        preference.dashboard_layout = layout
        self.db.commit()
        self.db.refresh(preference)
        return preference
