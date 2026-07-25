"""
Automatic schema migration.
Compares SQLAlchemy models with actual database schema and applies changes.
"""

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Tables that are not part of the application models and should be ignored.
_SKIP_TABLES = {"schema_migrations", "alembic_version"}


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

    def create_missing_tables(self) -> int:
        """Create tables that exist in models but not in database."""
        existing_tables = self.get_existing_tables()
        model_tables = set(self.base.metadata.tables.keys())
        missing_tables = model_tables - existing_tables

        if not missing_tables:
            return 0

        created_count = 0
        for table_name in missing_tables:
            if table_name in _SKIP_TABLES:
                continue
            try:
                logger.info("Creating missing table: %s", table_name)
                table = self.base.metadata.tables[table_name]
                table.create(bind=self.engine)
                created_count += 1
                logger.info("Created table: %s", table_name)
            except Exception as e:
                logger.error("Failed to create table %s: %s", table_name, e)

        return created_count

    def add_missing_columns(self) -> int:
        """Add columns that exist in models but not in database."""
        existing_tables = self.get_existing_tables()
        added_count = 0

        for table_name, table in self.base.metadata.tables.items():
            if table_name not in existing_tables or table_name in _SKIP_TABLES:
                continue

            existing_columns = self.get_existing_columns(table_name)
            model_columns = {col.name: col for col in table.columns}
            missing_columns = set(model_columns.keys()) - existing_columns

            if not missing_columns:
                continue

            for col_name in missing_columns:
                try:
                    column = model_columns[col_name]

                    if column.primary_key:
                        logger.warning("Skipping primary key column %s in %s", col_name, table_name)
                        continue

                    col_def = self.get_column_definition(column)
                    alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}"

                    logger.info("Adding column %s.%s", table_name, col_name)
                    logger.debug("SQL: %s", alter_sql)

                    with self.engine.connect() as conn:
                        conn.execute(text(alter_sql))
                        conn.commit()

                    added_count += 1
                    logger.info("Added column: %s.%s", table_name, col_name)

                except Exception as e:
                    logger.error("Failed to add column %s.%s: %s", table_name, col_name, e)

        return added_count

    def create_missing_indexes(self) -> int:
        """Create indexes that exist in models but not in database."""
        existing_tables = self.get_existing_tables()
        created_count = 0

        for table_name, table in self.base.metadata.tables.items():
            if table_name not in existing_tables or table_name in _SKIP_TABLES:
                continue

            existing_indexes = self.get_existing_indexes(table_name)

            for index in table.indexes:
                if index.name and index.name not in existing_indexes:
                    try:
                        logger.info("Creating index %s on %s", index.name, table_name)
                        index.create(bind=self.engine)
                        created_count += 1
                        logger.info("Created index: %s", index.name)
                    except Exception as e:
                        logger.warning("Failed to create index %s: %s", index.name, e)

        return created_count

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
