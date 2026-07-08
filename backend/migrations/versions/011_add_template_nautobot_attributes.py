from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

ADD_NAUTOBOT_ATTRIBUTES_COLUMN = """
ALTER TABLE templates
ADD COLUMN IF NOT EXISTS nautobot_attributes TEXT
"""


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "011_add_template_nautobot_attributes"

    @property
    def description(self) -> str:
        return "Add nautobot_attributes preview selection to templates"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(ADD_NAUTOBOT_ATTRIBUTES_COLUMN))
        return {"columns_added": ["nautobot_attributes"]}
