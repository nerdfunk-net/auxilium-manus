"""Area 3 — database bootstrap: init_db, schema sync, health.

Runs against the real ``manus_test`` Postgres created by the session
``_bootstrap_db`` fixture.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

from core.database import init_db, ping_database
from core.models import Base
from migrations.auto_schema import AutoSchemaMigration

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("require_postgres")]

from tests.integration.conftest import ENGINE  # noqa: E402


def test_all_model_tables_exist() -> None:
    existing = set(inspect(ENGINE).get_table_names())
    expected = set(Base.metadata.tables.keys())
    missing = expected - existing
    assert not missing, f"init_db did not create: {sorted(missing)}"


def test_init_db_is_idempotent() -> None:
    # A second run against an already-synced DB makes zero structural changes.
    auto = AutoSchemaMigration(ENGINE, Base)
    results = auto.run()
    assert results == {"tables_created": 0, "columns_added": 0, "indexes_created": 0}


def test_no_schema_drift_against_models() -> None:
    diff = AutoSchemaMigration(ENGINE, Base).analyze()
    assert diff.has_differences is False, (
        f"schema drift: missing_tables={diff.missing_tables} "
        f"missing_columns={diff.missing_columns} column_diffs={diff.column_diffs} "
        f"missing_indexes={diff.missing_indexes}"
    )


def test_ping_database_succeeds() -> None:
    ping_database()  # raises on failure


def test_ping_database_raises_on_bad_url() -> None:
    from sqlalchemy.exc import OperationalError

    bad = create_engine("postgresql+psycopg://nobody:nobody@127.0.0.1:1/nope")
    with pytest.raises(OperationalError):
        with bad.connect() as conn:
            conn.execute(text("SELECT 1"))


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("workflows", "name"),
        ("credentials", "owner_user_id"),
        ("workflow_step_results", "run_id"),
    ],
)
def test_declared_indexes_present(table: str, column: str) -> None:
    index_columns = {
        tuple(ix["column_names"]) for ix in inspect(ENGINE).get_indexes(table)
    }
    flat = {col for cols in index_columns for col in cols}
    assert column in flat, f"no index covering {table}.{column}: {index_columns}"


def test_init_db_callable_again_without_error() -> None:
    init_db()
