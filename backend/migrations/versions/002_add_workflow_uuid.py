from __future__ import annotations

import uuid as uuid_mod
from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

ADD_UUID_COLUMN = """
ALTER TABLE workflows
ADD COLUMN IF NOT EXISTS uuid VARCHAR(36) UNIQUE
"""

CREATE_UUID_INDEX = "CREATE UNIQUE INDEX IF NOT EXISTS ix_workflows_uuid ON workflows (uuid)"


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "002_add_workflow_uuid"

    @property
    def description(self) -> str:
        return "Add immutable UUID column to workflows table"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(ADD_UUID_COLUMN))
            # Backfill existing rows that have no uuid yet
            rows = conn.execute(text("SELECT id FROM workflows WHERE uuid IS NULL")).fetchall()
            for row in rows:
                conn.execute(
                    text("UPDATE workflows SET uuid = :uuid WHERE id = :id"),
                    {"uuid": str(uuid_mod.uuid4()), "id": row[0]},
                )
            conn.execute(text(CREATE_UUID_INDEX))
        return {"columns_added": ["workflows.uuid"], "rows_backfilled": len(rows)}
