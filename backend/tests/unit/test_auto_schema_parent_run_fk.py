"""workflow_runs.parent_run_id (start-workflow) is a self-referencing FK added to a live table.

An upgraded database must get the column together with its ON DELETE SET NULL constraint, so a
purged parent run leaves the child in place (same rule as ``test_auto_schema_foreign_key``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.models.base import Base
from core.models.runs import WorkflowRun
from migrations.auto_schema import AutoSchemaMigration


def test_parent_run_id_is_added_with_its_self_referencing_constraint() -> None:
    migration = AutoSchemaMigration(MagicMock(), Base)
    statements = migration.foreign_key_statements(WorkflowRun.__table__.columns["parent_run_id"])
    assert len(statements) == 1
    assert "FOREIGN KEY (parent_run_id) REFERENCES workflow_runs (id)" in statements[0]
    assert statements[0].endswith("ON DELETE SET NULL")
