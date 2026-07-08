from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

ADD_PRE_RUN_COMMANDS_COLUMN = """
ALTER TABLE templates
ADD COLUMN IF NOT EXISTS pre_run_commands TEXT
"""

ADD_PRE_RUN_USE_TEXTFSM_COLUMN = """
ALTER TABLE templates
ADD COLUMN IF NOT EXISTS pre_run_use_textfsm BOOLEAN NOT NULL DEFAULT FALSE
"""

# Seed the new list column from the legacy single-command field so existing
# templates keep their configured pre-run command after the upgrade.
BACKFILL_PRE_RUN_COMMANDS = """
UPDATE templates
SET pre_run_commands = json_build_array(pre_run_command)::text
WHERE pre_run_commands IS NULL
  AND pre_run_command IS NOT NULL
  AND pre_run_command <> ''
"""


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "010_add_template_pre_run_commands"

    @property
    def description(self) -> str:
        return "Add multi-command pre-run support (pre_run_commands, pre_run_use_textfsm)"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(ADD_PRE_RUN_COMMANDS_COLUMN))
            conn.execute(text(ADD_PRE_RUN_USE_TEXTFSM_COLUMN))
            conn.execute(text(BACKFILL_PRE_RUN_COMMANDS))
        return {"columns_added": ["pre_run_commands", "pre_run_use_textfsm"]}
