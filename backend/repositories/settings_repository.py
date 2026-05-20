from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.settings import Setting


class SettingsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_key(self, key: str) -> Setting | None:
        return self.db.scalar(select(Setting).where(Setting.key == key))

    def list_all(self, *, key_prefix: str | None = None) -> list[Setting]:
        stmt = select(Setting).order_by(Setting.key.asc())
        if key_prefix:
            stmt = stmt.where(Setting.key.startswith(key_prefix))
        return list(self.db.scalars(stmt))

    def create(
        self,
        *,
        key: str,
        value: dict[str, Any],
        description: str | None,
    ) -> Setting:
        setting = Setting(key=key, value=value, description=description)
        self.db.add(setting)
        self.db.commit()
        self.db.refresh(setting)
        return setting

    def update(self, setting: Setting, fields: dict[str, Any]) -> Setting:
        for field_key, field_value in fields.items():
            setattr(setting, field_key, field_value)
        self.db.commit()
        self.db.refresh(setting)
        return setting

    def delete(self, setting: Setting) -> None:
        self.db.delete(setting)
        self.db.commit()
