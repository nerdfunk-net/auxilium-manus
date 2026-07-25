"""Pydantic models for database schema sync status/migration endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class TableColumnRef(BaseModel):
    table: str
    column: str


class TableIndexRef(BaseModel):
    table: str
    index: str


class ColumnDiffOut(BaseModel):
    table: str
    column: str
    db_type: str
    model_type: str
    type_changed: bool
    nullable_changed: bool
    db_nullable: bool
    model_nullable: bool
    safe: bool


class SchemaStatusResponse(BaseModel):
    is_up_to_date: bool
    missing_tables: list[str]
    extra_tables: list[str]
    missing_columns: list[TableColumnRef]
    extra_columns: list[TableColumnRef]
    column_diffs: list[ColumnDiffOut]
    missing_indexes: list[TableIndexRef]
    extra_indexes: list[TableIndexRef]


class SchemaMigrationResponse(BaseModel):
    success: bool
    message: str
    tables_created: int
    columns_added: int
    indexes_created: int
    column_changes_applied: list[str]
    column_changes_skipped: list[str]
    errors: list[str]
