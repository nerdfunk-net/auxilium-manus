from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

CREATE_WORKFLOWS_TABLE = """
CREATE TABLE IF NOT EXISTS workflows (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    creator_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    description VARCHAR(2000),
    folder      VARCHAR(500) DEFAULT '/',
    visibility  VARCHAR(10) NOT NULL DEFAULT 'private',
    canvas_nodes JSONB,
    canvas_edges JSONB,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
)
"""

CREATE_WORKFLOWS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_workflows_name ON workflows (name)",
    "CREATE INDEX IF NOT EXISTS ix_workflows_creator_id ON workflows (creator_id)",
    "CREATE INDEX IF NOT EXISTS ix_workflows_visibility ON workflows (visibility)",
]


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "001_create_workflows_table"

    @property
    def description(self) -> str:
        return "Create workflows table for storing visual workflow definitions"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(CREATE_WORKFLOWS_TABLE))
            for idx_sql in CREATE_WORKFLOWS_INDEXES:
                conn.execute(text(idx_sql))
        return {"tables_created": ["workflows"]}
