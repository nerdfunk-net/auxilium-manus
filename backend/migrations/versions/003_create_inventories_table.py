from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

CREATE_INVENTORIES_TABLE = """
CREATE TABLE IF NOT EXISTS inventories (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    conditions      TEXT NOT NULL,
    template_category VARCHAR(255),
    template_name   VARCHAR(255),
    scope           VARCHAR(50) NOT NULL DEFAULT 'global',
    group_path      VARCHAR(1000),
    created_by      VARCHAR(255) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
)
"""

CREATE_INVENTORIES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_inventories_name ON inventories (name)",
    "CREATE INDEX IF NOT EXISTS ix_inventories_created_by ON inventories (created_by)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_scope_created_by ON inventories (scope, created_by)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_active_scope ON inventories (is_active, scope)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_group_path ON inventories (group_path)",
]


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "003_create_inventories_table"

    @property
    def description(self) -> str:
        return "Create inventories table for saved Nautobot device selections"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(CREATE_INVENTORIES_TABLE))
            for idx_sql in CREATE_INVENTORIES_INDEXES:
                conn.execute(text(idx_sql))
        return {"tables_created": ["inventories"]}
