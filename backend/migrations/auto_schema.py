"""
Automatic schema migration.
Compares SQLAlchemy models with actual database schema and applies changes.
"""

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import AddConstraint, sort_tables_and_constraints

logger = logging.getLogger(__name__)

# Tables that are not part of the application models and should be ignored.
_SKIP_TABLES = {"schema_migrations", "alembic_version"}


def pg_cast(canonical_type: str) -> str:
    """Map a canonical column type (see normalize_pg_type) to the PostgreSQL
    cast target used in `USING col::<cast>` when changing a column's type."""
    _map = {
        "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ",
        "DOUBLE PRECISION": "DOUBLE PRECISION",
    }
    return _map.get(canonical_type, canonical_type)


def normalize_pg_type(type_str: str) -> str:
    """Normalize a PostgreSQL type string to a canonical form for comparison."""
    t = type_str.upper().strip()

    if t.startswith("VARCHAR") or t.startswith("CHARACTER VARYING"):
        match = re.search(r"\((\d+)\)", t)
        return f"VARCHAR({match.group(1)})" if match else "VARCHAR"

    if t in ("INTEGER", "INT", "INT4"):
        return "INTEGER"
    if t in ("BIGINT", "INT8"):
        return "BIGINT"
    if t in ("SMALLINT", "INT2"):
        return "SMALLINT"

    if "TIMESTAMP" in t:
        if "TIME ZONE" in t or t == "TIMESTAMPTZ":
            return "TIMESTAMP WITH TIME ZONE"
        return "TIMESTAMP"

    if t in ("BOOLEAN", "BOOL"):
        return "BOOLEAN"
    if t in ("FLOAT", "FLOAT4", "FLOAT8", "REAL", "DOUBLE PRECISION"):
        return "FLOAT"
    if t in ("SERIAL", "SERIAL4"):
        return "INTEGER"
    if t == "BIGSERIAL":
        return "BIGINT"

    return t


def _is_safe_type_change(from_type: str, to_type: str) -> bool:
    """True when the type change carries no data-loss risk."""
    if from_type == to_type:
        return True
    if from_type.startswith("VARCHAR") and to_type == "TEXT":
        return True
    if from_type.startswith("VARCHAR") and to_type.startswith("VARCHAR"):
        m1 = re.search(r"\((\d+)\)", from_type)
        m2 = re.search(r"\((\d+)\)", to_type)
        if m1 and m2:
            return int(m2.group(1)) > int(m1.group(1))
    if from_type == "TIMESTAMP" and to_type == "TIMESTAMP WITH TIME ZONE":
        return True
    if from_type == "INTEGER" and to_type == "BIGINT":
        return True
    if from_type == "SMALLINT" and to_type in ("INTEGER", "BIGINT"):
        return True
    return False


@dataclass
class ColumnDiff:
    table: str
    column: str
    db_type: str
    model_type: str
    db_nullable: bool
    model_nullable: bool

    @property
    def type_changed(self) -> bool:
        return self.db_type != self.model_type

    @property
    def nullable_changed(self) -> bool:
        return self.db_nullable != self.model_nullable

    @property
    def safe(self) -> bool:
        """True if the change can be applied without data-loss risk."""
        # Adding a NOT NULL constraint is risky when the column may have NULLs.
        if self.nullable_changed and not self.model_nullable:
            return False
        if not self.type_changed:
            return True
        return _is_safe_type_change(self.db_type, self.model_type)


@dataclass
class SchemaDiff:
    missing_tables: list[str] = field(default_factory=list)
    extra_tables: list[str] = field(default_factory=list)
    missing_columns: list[tuple[str, str]] = field(default_factory=list)
    extra_columns: list[tuple[str, str]] = field(default_factory=list)
    column_diffs: list[ColumnDiff] = field(default_factory=list)
    missing_indexes: list[tuple[str, str]] = field(default_factory=list)
    extra_indexes: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_differences(self) -> bool:
        return bool(
            self.missing_tables or self.missing_columns or self.column_diffs or self.missing_indexes
        )


@dataclass
class ApplyResult:
    """Outcome of applying one batch of schema changes (columns, indexes, or
    column type/nullable diffs). `succeeded`/`failed` entries are display
    labels (e.g. "table.column"), not raw identifiers. Shared by
    AutoSchemaMigration's apply methods so callers (run(), SchemaManager,
    scripts/database/sync.py) don't each format their own."""

    succeeded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class TableCreationResult:
    """Outcome of AutoSchemaMigration.create_tables(). Constraints are
    reported separately from tables because a FK constraint broken out of a
    table-level cycle (see create_tables) is applied afterwards, as its own
    ALTER TABLE step."""

    created: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    constraints_added: list[str] = field(default_factory=list)
    constraints_failed: list[tuple[str, str]] = field(default_factory=list)


class AutoSchemaMigration:
    """
    Automatic database schema synchronization.
    Detects missing tables, columns, and indexes and creates them.
    """

    def __init__(self, engine: Engine, base):
        self.engine = engine
        self.base = base
        self.inspector = inspect(engine)

    def get_existing_tables(self) -> set[str]:
        """Get all existing table names in the database."""
        return set(self.inspector.get_table_names())

    def get_existing_columns(self, table_name: str) -> set[str]:
        """Get all existing column names for a table."""
        try:
            columns = self.inspector.get_columns(table_name)
            return {col["name"] for col in columns}
        except Exception:
            return set()

    def get_existing_indexes(self, table_name: str) -> set[str]:
        """Get all existing index names for a table."""
        try:
            indexes = self.inspector.get_indexes(table_name)
            return {idx["name"] for idx in indexes}
        except Exception:
            return set()

    def sqlalchemy_type_to_sql(self, column) -> str:
        """Convert SQLAlchemy column type to PostgreSQL SQL type string."""
        return self._type_to_canonical(column.type)

    def _type_to_canonical(self, type_obj) -> str:
        """
        Convert a SQLAlchemy type object to a canonical PostgreSQL type string.

        Accepts type objects from both model column definitions and the
        SQLAlchemy inspector — using isinstance rather than str() avoids
        dialect-specific rendering differences (e.g. str(TIMESTAMP(tz=True))
        can return "DATETIME" under the default dialect instead of
        "TIMESTAMP WITH TIME ZONE").
        """
        from sqlalchemy import (
            BigInteger,
            Boolean,
            DateTime,
            Float,
            Integer,
            LargeBinary,
            Numeric,
            SmallInteger,
            String,
            Text,
        )

        try:
            from sqlalchemy.dialects.postgresql import JSON, JSONB
        except ImportError:
            JSONB = None  # type: ignore[assignment]
            JSON = None  # type: ignore[assignment]

        if JSONB and isinstance(type_obj, JSONB):
            return "JSONB"
        if JSON and isinstance(type_obj, JSON):
            return "JSON"
        # String / VARCHAR — check before Text since Text is a subclass of String
        if isinstance(type_obj, Text):
            return "TEXT"
        if isinstance(type_obj, String):
            return f"VARCHAR({type_obj.length})" if type_obj.length else "TEXT"
        if isinstance(type_obj, BigInteger):
            return "BIGINT"
        if isinstance(type_obj, SmallInteger):
            return "SMALLINT"
        if isinstance(type_obj, Integer):
            return "INTEGER"
        if isinstance(type_obj, Boolean):
            return "BOOLEAN"
        if isinstance(type_obj, DateTime):
            return (
                "TIMESTAMP WITH TIME ZONE" if getattr(type_obj, "timezone", False) else "TIMESTAMP"
            )
        if isinstance(type_obj, LargeBinary):
            return "BYTEA"
        if isinstance(type_obj, Float):
            return "FLOAT"
        if isinstance(type_obj, Numeric):
            return "NUMERIC"
        # Fallback: normalize whatever str() returns
        return normalize_pg_type(str(type_obj))

    # Keep old name as alias for callers that passed a column object.
    def _sqlalchemy_type_to_canonical(self, column) -> str:
        return self._type_to_canonical(column.type)

    def get_column_definition(self, column) -> str:
        """Generate SQL column definition from SQLAlchemy column."""
        sql_type = self._sqlalchemy_type_to_canonical(column)
        parts = [sql_type]

        if not column.nullable:
            parts.append("NOT NULL")

        if column.default is not None:
            default_value = column.default
            if hasattr(default_value, "arg"):
                if "now()" in str(default_value.arg).lower():
                    parts.append("DEFAULT CURRENT_TIMESTAMP")
                elif isinstance(default_value.arg, bool):
                    parts.append(f"DEFAULT {str(default_value.arg).upper()}")
                elif isinstance(default_value.arg, (int, float)):
                    parts.append(f"DEFAULT {default_value.arg}")
                elif isinstance(default_value.arg, str):
                    parts.append(f"DEFAULT '{default_value.arg}'")
        elif column.server_default is not None:
            default_text = str(column.server_default.arg)
            if "now()" in default_text.lower():
                parts.append("DEFAULT CURRENT_TIMESTAMP")

        return " ".join(parts)

    # ------------------------------------------------------------------
    # Schema analysis (used by sync.py)
    # ------------------------------------------------------------------

    def analyze(self, table_filter: str | None = None) -> SchemaDiff:
        """
        Compare SQLAlchemy model definitions against the live database schema.

        Returns a SchemaDiff describing all detected differences.
        Does NOT modify the database.
        """
        diff = SchemaDiff()
        existing_tables = self.get_existing_tables()

        model_tables = {k: v for k, v in self.base.metadata.tables.items() if k not in _SKIP_TABLES}
        if table_filter:
            model_tables = {k: v for k, v in model_tables.items() if k == table_filter}

        model_table_names = set(model_tables.keys())

        diff.missing_tables = sorted(model_table_names - existing_tables)
        diff.extra_tables = sorted((existing_tables - model_table_names) - _SKIP_TABLES)

        for table_name, table in sorted(model_tables.items()):
            if table_name not in existing_tables:
                continue

            db_cols = {c["name"]: c for c in self.inspector.get_columns(table_name)}
            model_cols = {c.name: c for c in table.columns}

            # Missing columns (in model, absent from DB)
            for col_name in sorted(set(model_cols) - set(db_cols)):
                col = model_cols[col_name]
                if not col.primary_key:
                    diff.missing_columns.append((table_name, col_name))

            # Extra columns (in DB, absent from model)
            for col_name in sorted(set(db_cols) - set(model_cols)):
                diff.extra_columns.append((table_name, col_name))

            # Type / nullability changes for columns present in both
            for col_name in sorted(set(model_cols) & set(db_cols)):
                model_col = model_cols[col_name]
                if model_col.primary_key:
                    continue
                db_col = db_cols[col_name]

                model_type = self._type_to_canonical(model_col.type)
                db_type = self._type_to_canonical(db_col["type"])
                model_nullable = bool(model_col.nullable)
                db_nullable = bool(db_col["nullable"])

                if model_type != db_type or model_nullable != db_nullable:
                    diff.column_diffs.append(
                        ColumnDiff(
                            table=table_name,
                            column=col_name,
                            db_type=db_type,
                            model_type=model_type,
                            db_nullable=db_nullable,
                            model_nullable=model_nullable,
                        )
                    )

            # Indexes -------------------------------------------------------
            # Fetch full index info so we can inspect uniqueness and columns.
            db_indexes = {idx["name"]: idx for idx in self.inspector.get_indexes(table_name)}
            existing_idx_names = set(db_indexes.keys())
            model_idx_names = {idx.name for idx in table.indexes if idx.name}

            # Build the column-sets that back unique constraints in the model.
            # PostgreSQL implements UNIQUE constraints as indexes, but SQLAlchemy
            # stores them in table.constraints (not table.indexes), so we must
            # check both to avoid false "extra index" reports.
            from sqlalchemy import UniqueConstraint

            model_unique_col_sets: set[frozenset] = set()
            for constraint in table.constraints:
                if isinstance(constraint, UniqueConstraint) and constraint.columns:
                    model_unique_col_sets.add(frozenset(c.name for c in constraint.columns))
            for col in table.columns:
                if col.unique and not col.primary_key:
                    model_unique_col_sets.add(frozenset([col.name]))

            for idx in sorted(table.indexes, key=lambda i: i.name or ""):
                if idx.name and idx.name not in existing_idx_names:
                    diff.missing_indexes.append((table_name, idx.name))

            for idx_name in sorted(existing_idx_names - model_idx_names):
                # Skip primary-key backing indexes.
                if idx_name.endswith("_pkey"):
                    continue
                # Skip unique-constraint backing indexes that match a model
                # UniqueConstraint — PostgreSQL names these automatically (e.g.
                # "roles_name_key") and they don't appear in table.indexes.
                idx_info = db_indexes[idx_name]
                if idx_info.get("unique"):
                    col_set = frozenset(idx_info.get("column_names", []))
                    if col_set in model_unique_col_sets:
                        continue
                diff.extra_indexes.append((table_name, idx_name))

        return diff

    # ------------------------------------------------------------------
    # Schema application (used by startup and sync.py --migrate)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Apply primitives — the single implementation of "how to create
    # tables / add columns / create indexes / apply column diffs".
    #
    # Both the automatic startup sync (run(), below) and the manual
    # `scripts/database/sync.py --migrate` CLI call these same methods
    # (the latter via the diff it already computed with analyze(), so
    # `--table` filtering is respected) instead of each keeping its own
    # copy — see doc/MIGRATION_SYSTEM.md. core.schema_manager.SchemaManager
    # (the HTTP-facing admin "sync schema" action) also builds on these via
    # apply_column_diffs() for the safe/risky type-change split.
    # ------------------------------------------------------------------

    def create_tables(self, table_names: Iterable[str]) -> TableCreationResult:
        """Create the named tables, in FK-dependency order.

        Unlike plain `metadata.sorted_tables`, sort_tables_and_constraints()
        pulls any use_alter=True foreign key (see WorkflowRun.change_request_id)
        out of its table's CREATE TABLE and returns it separately, so a
        table-level FK cycle (e.g. change_requests <-> workflow_runs) doesn't
        block ordering of the rest of the graph. That constraint is then
        added via a deferred ALTER TABLE once every table exists.
        """
        result = TableCreationResult()
        names = {n for n in table_names if n not in _SKIP_TABLES}
        if not names:
            return result

        tables = [t for t in self.base.metadata.tables.values() if t.name in names]
        ordered = sort_tables_and_constraints(tables)

        deferred_constraints = []
        for table, fkcs in ordered:
            # table is None for the trailing entry that carries constraints
            # sort_tables_and_constraints() pulled out of inline CREATE TABLE
            # (use_alter=True, or ones it had to break to resolve a cycle) —
            # every other entry's fkcs are the ones table.create() already
            # renders inline, listed here for informational purposes only.
            if table is None:
                deferred_constraints.extend(fkcs)
                continue
            try:
                logger.info("Creating missing table: %s", table.name)
                table.create(bind=self.engine)
                result.created.append(table.name)
                logger.info("Created table: %s", table.name)
            except Exception as e:
                logger.error("Failed to create table %s: %s", table.name, e)
                result.failed.append((table.name, str(e)))

        for fkc in deferred_constraints:
            try:
                logger.info(
                    "Adding deferred foreign key constraint %s on %s", fkc.name, fkc.table.name
                )
                with self.engine.begin() as conn:
                    conn.execute(AddConstraint(fkc))
                result.constraints_added.append(fkc.name)
                logger.info("Added deferred foreign key constraint: %s", fkc.name)
            except Exception as e:
                logger.error("Failed to add deferred foreign key constraint %s: %s", fkc.name, e)
                result.constraints_failed.append((fkc.name, str(e)))

        return result

    def add_columns(self, columns: Iterable[tuple[str, str]]) -> ApplyResult:
        """Add the given (table_name, column_name) columns via ALTER TABLE."""
        result = ApplyResult()
        for table_name, col_name in columns:
            label = f"{table_name}.{col_name}"
            try:
                table = self.base.metadata.tables[table_name]
                column = next(c for c in table.columns if c.name == col_name)

                if column.primary_key:
                    logger.warning("Skipping primary key column %s in %s", col_name, table_name)
                    continue

                col_def = self.get_column_definition(column)
                alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}"

                logger.info("Adding column %s", label)
                logger.debug("SQL: %s", alter_sql)

                with self.engine.connect() as conn:
                    conn.execute(text(alter_sql))
                    conn.commit()

                result.succeeded.append(label)
                logger.info("Added column: %s", label)

            except Exception as e:
                logger.error("Failed to add column %s: %s", label, e)
                result.failed.append((label, str(e)))

        return result

    def create_indexes(self, indexes: Iterable[tuple[str, str]]) -> ApplyResult:
        """Create the given (table_name, index_name) indexes."""
        result = ApplyResult()
        for table_name, idx_name in indexes:
            try:
                table = self.base.metadata.tables.get(table_name)
                if table is None:
                    continue
                index = next((i for i in table.indexes if i.name == idx_name), None)
                if index is None:
                    continue
                logger.info("Creating index %s on %s", idx_name, table_name)
                index.create(bind=self.engine)
                result.succeeded.append(idx_name)
                logger.info("Created index: %s", idx_name)
            except Exception as e:
                logger.warning("Failed to create index %s: %s", idx_name, e)
                result.failed.append((idx_name, str(e)))

        return result

    def apply_column_diffs(self, diff: SchemaDiff, force: bool = False) -> ApplyResult:
        """Apply type/nullable changes from `diff.column_diffs`.

        Safe changes (see ColumnDiff.safe) are always applied; risky ones
        (may truncate data, or add NOT NULL to a column that may hold NULLs)
        are only applied when force=True, and reported in `skipped` otherwise.
        """
        result = ApplyResult()
        for cd in sorted(diff.column_diffs, key=lambda d: (d.table, d.column)):
            label = f"{cd.table}.{cd.column}"
            if not cd.safe and not force:
                result.skipped.append(label)
                continue

            stmts = []
            if cd.type_changed:
                cast = pg_cast(cd.model_type)
                stmts.append(
                    f"ALTER COLUMN {cd.column} TYPE {cd.model_type} USING {cd.column}::{cast}"
                )
            if cd.nullable_changed:
                stmt = "DROP NOT NULL" if cd.model_nullable else "SET NOT NULL"
                stmts.append(f"ALTER COLUMN {cd.column} {stmt}")

            change = f"{cd.db_type} -> {cd.model_type}" if cd.type_changed else "nullable changed"
            try:
                for stmt in stmts:
                    with self.engine.connect() as conn:
                        conn.execute(text(f"ALTER TABLE {cd.table} {stmt}"))
                        conn.commit()
                result.succeeded.append(f"{label} ({change})")
                logger.info("Changed: %s (%s)", label, change)
            except Exception as e:
                logger.error("Failed to alter %s: %s", label, e)
                result.failed.append((label, "failed to apply"))

        return result

    # ------------------------------------------------------------------
    # Diff-driven wrappers — compute what's missing for the *whole* schema
    # and apply it via the primitives above. Used by run() (startup).
    # ------------------------------------------------------------------

    def create_missing_tables(self) -> int:
        """Create tables that exist in models but not in database."""
        existing_tables = self.get_existing_tables()
        model_tables = set(self.base.metadata.tables.keys())
        missing_tables = model_tables - existing_tables
        return len(self.create_tables(missing_tables).created)

    def add_missing_columns(self) -> int:
        """Add columns that exist in models but not in database."""
        existing_tables = self.get_existing_tables()
        pairs: list[tuple[str, str]] = []

        for table_name, table in self.base.metadata.tables.items():
            if table_name not in existing_tables or table_name in _SKIP_TABLES:
                continue
            existing_columns = self.get_existing_columns(table_name)
            missing_columns = {col.name for col in table.columns} - existing_columns
            pairs.extend((table_name, col_name) for col_name in missing_columns)

        return len(self.add_columns(pairs).succeeded)

    def create_missing_indexes(self) -> int:
        """Create indexes that exist in models but not in database."""
        existing_tables = self.get_existing_tables()
        pairs: list[tuple[str, str]] = []

        for table_name, table in self.base.metadata.tables.items():
            if table_name not in existing_tables or table_name in _SKIP_TABLES:
                continue
            existing_indexes = self.get_existing_indexes(table_name)
            pairs.extend(
                (table_name, index.name)
                for index in table.indexes
                if index.name and index.name not in existing_indexes
            )

        return len(self.create_indexes(pairs).succeeded)

    def run(self) -> dict[str, int]:
        """
        Execute automatic schema synchronization (safe operations only).
        Called on application startup.
        Returns statistics about changes made.
        """
        results = {
            "tables_created": 0,
            "columns_added": 0,
            "indexes_created": 0,
        }

        try:
            results["tables_created"] = self.create_missing_tables()
            # Re-inspect after table creation so column checks see the new tables.
            self.inspector = inspect(self.engine)
            results["columns_added"] = self.add_missing_columns()
            results["indexes_created"] = self.create_missing_indexes()
        except Exception as e:
            logger.error("Schema migration failed: %s", e)
            raise

        return results
