from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

ADD_APPROVAL_STATE_COLUMN = """
ALTER TABLE workflow_runs
ADD COLUMN IF NOT EXISTS approval_state JSONB
"""


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "015_add_run_approval_state"

    @property
    def description(self) -> str:
        return "Add approval_state column to workflow_runs for Wait & Run batching"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(ADD_APPROVAL_STATE_COLUMN))
        return {"columns_added": ["workflow_runs.approval_state"]}
