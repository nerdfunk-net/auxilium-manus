from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(255) NOT NULL,
    password_hash VARCHAR(512) NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
)
"""

CREATE_USERS_USERNAME_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"
)


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "000_create_users_table"

    @property
    def description(self) -> str:
        return "Create users table (must run before any table with a users FK)"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(CREATE_USERS_TABLE))
            conn.execute(text(CREATE_USERS_USERNAME_INDEX))
        return {"tables_created": ["users"]}
