from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

CREATE_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    id          SERIAL PRIMARY KEY,
    key         VARCHAR(255) NOT NULL UNIQUE,
    value       JSONB NOT NULL DEFAULT '{}',
    description TEXT,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
)
"""

CREATE_SETTINGS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_settings_key ON settings (key)",
]


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "004_create_settings_table"

    @property
    def description(self) -> str:
        return "Create settings table for application configuration"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(CREATE_SETTINGS_TABLE))
            for idx_sql in CREATE_SETTINGS_INDEXES:
                conn.execute(text(idx_sql))
        return {"tables_created": ["settings"]}
