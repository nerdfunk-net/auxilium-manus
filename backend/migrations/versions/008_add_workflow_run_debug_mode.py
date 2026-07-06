from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

ADD_RUN_MODE_COLUMN = """
ALTER TABLE workflow_runs
ADD COLUMN IF NOT EXISTS run_mode VARCHAR(20) NOT NULL DEFAULT 'normal'
"""

ADD_CURRENT_NODE_ID_COLUMN = """
ALTER TABLE workflow_runs
ADD COLUMN IF NOT EXISTS current_node_id VARCHAR(255)
"""

ADD_DEBUG_MESSAGE_COLUMN = """
ALTER TABLE workflow_runs
ADD COLUMN IF NOT EXISTS debug_message TEXT
"""


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "008_add_workflow_run_debug_mode"

    @property
    def description(self) -> str:
        return (
            "Add run_mode, current_node_id, debug_message columns to "
            "workflow_runs for step-by-step debug execution"
        )

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(ADD_RUN_MODE_COLUMN))
            conn.execute(text(ADD_CURRENT_NODE_ID_COLUMN))
            conn.execute(text(ADD_DEBUG_MESSAGE_COLUMN))
        return {
            "columns_added": [
                "workflow_runs.run_mode",
                "workflow_runs.current_node_id",
                "workflow_runs.debug_message",
            ]
        }
