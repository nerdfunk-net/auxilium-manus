from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

CREATE_WORKFLOW_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    id              SERIAL PRIMARY KEY,
    uuid            VARCHAR(36)  NOT NULL UNIQUE,
    workflow_id     INTEGER      NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    triggered_by_id INTEGER      REFERENCES users(id) ON DELETE SET NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    trigger_type    VARCHAR(20)  NOT NULL DEFAULT 'manual',
    device_ids      JSONB,
    hatchet_run_id  VARCHAR(255),
    error_message   TEXT,
    started_at      TIMESTAMP WITH TIME ZONE,
    finished_at     TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
)
"""

CREATE_WORKFLOW_STEP_RESULTS_TABLE = """
CREATE TABLE IF NOT EXISTS workflow_step_results (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER      NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    step_node_id    VARCHAR(255) NOT NULL,
    step_type       VARCHAR(100) NOT NULL,
    step_name       VARCHAR(255) NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMP WITH TIME ZONE,
    finished_at     TIMESTAMP WITH TIME ZONE,
    output          JSONB,
    error_message   TEXT,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
)
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_workflow_runs_uuid ON workflow_runs (uuid)",
    "CREATE INDEX IF NOT EXISTS ix_workflow_runs_workflow_id ON workflow_runs (workflow_id)",
    "CREATE INDEX IF NOT EXISTS ix_workflow_runs_triggered_by_id ON workflow_runs (triggered_by_id)",
    "CREATE INDEX IF NOT EXISTS ix_workflow_runs_status ON workflow_runs (status)",
    "CREATE INDEX IF NOT EXISTS ix_workflow_runs_hatchet_run_id ON workflow_runs (hatchet_run_id)",
    "CREATE INDEX IF NOT EXISTS ix_workflow_step_results_run_id ON workflow_step_results (run_id)",
]


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "005_create_workflow_runs_tables"

    @property
    def description(self) -> str:
        return "Create workflow_runs and workflow_step_results tables for execution tracking"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(CREATE_WORKFLOW_RUNS_TABLE))
            conn.execute(text(CREATE_WORKFLOW_STEP_RESULTS_TABLE))
            for idx_sql in INDEXES:
                conn.execute(text(idx_sql))
        return {"tables_created": ["workflow_runs", "workflow_step_results"]}
