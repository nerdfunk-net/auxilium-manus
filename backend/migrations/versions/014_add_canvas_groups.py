from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

ADD_CANVAS_GROUPS_COLUMN = """
ALTER TABLE workflows
ADD COLUMN IF NOT EXISTS canvas_groups JSONB NOT NULL DEFAULT '[]'
"""


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "014_add_canvas_groups"

    @property
    def description(self) -> str:
        return "Add canvas_groups editor metadata column to workflows"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(ADD_CANVAS_GROUPS_COLUMN))
        return {"columns_added": ["workflows.canvas_groups"]}
