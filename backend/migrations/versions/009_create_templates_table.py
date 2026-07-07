from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

CREATE_TEMPLATES_TABLE = """
CREATE TABLE IF NOT EXISTS templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'webeditor',
    template_type VARCHAR(50) NOT NULL DEFAULT 'jinja2',
    category VARCHAR(100) NOT NULL DEFAULT 'netmiko',
    description TEXT,
    content TEXT NOT NULL DEFAULT '',
    variables TEXT NOT NULL DEFAULT '{}',
    pre_run_command TEXT,
    credential_id INTEGER,
    created_by VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
)
"""

CREATE_TEMPLATES_ACTIVE_NAME_IDX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_templates_active_name
ON templates (name)
WHERE is_active
"""

CREATE_TEMPLATES_CATEGORY_IDX = """
CREATE INDEX IF NOT EXISTS idx_templates_category ON templates (category)
"""

CREATE_TEMPLATES_CREATED_BY_IDX = """
CREATE INDEX IF NOT EXISTS idx_templates_created_by ON templates (created_by)
"""


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "009_create_templates_table"

    @property
    def description(self) -> str:
        return "Create templates table for Jinja2 Netmiko configuration templates"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(CREATE_TEMPLATES_TABLE))
            conn.execute(text(CREATE_TEMPLATES_ACTIVE_NAME_IDX))
            conn.execute(text(CREATE_TEMPLATES_CATEGORY_IDX))
            conn.execute(text(CREATE_TEMPLATES_CREATED_BY_IDX))
        return {"tables_created": ["templates"]}
