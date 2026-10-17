"""
Database schema synchronization for Auxilium Manus.

AutoSchemaMigration compares SQLAlchemy models against the live PostgreSQL
schema and applies missing tables, columns, and indexes on startup.

For interactive checking and applying schema differences, use:
    python scripts/database/sync.py
"""

from .auto_schema import AutoSchemaMigration, ColumnDiff, SchemaDiff

__all__ = ["AutoSchemaMigration", "ColumnDiff", "SchemaDiff"]
