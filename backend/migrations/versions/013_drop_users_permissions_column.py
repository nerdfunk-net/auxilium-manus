from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

DROP_USERS_PERMISSIONS_COLUMN = """
ALTER TABLE users DROP COLUMN IF EXISTS permissions
"""


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "013_drop_users_permissions_column"

    @property
    def description(self) -> str:
        return "Drop the legacy users.permissions bitmask column, superseded by RBAC tables"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(DROP_USERS_PERMISSIONS_COLUMN))
        return {"columns_dropped": ["users.permissions"]}
