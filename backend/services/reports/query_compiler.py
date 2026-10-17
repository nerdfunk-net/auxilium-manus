"""Compile a declarative ``ReportQuery`` into a SQLAlchemy statement and run it.

Safety: the query is validated against the dataset's catalog entry first, field names only ever
reach SQL as bound JSON-path parameters, and no SQL is built from strings.
Rows are read from either the newest collection per device (scope ``latest``) or from every
collection (scope ``history``); both exclude the empty-collection marker rows, except for a query
that uses ``count_devices`` / ``count_items``, which reads them so a device with no items shows up
as a device with zero items.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    case,
    cast,
    distinct,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from core.models.report_data_records import ReportDataRecord
from models.reports import (
    COLLECTED_AT_FIELD,
    DEVICE_METRIC_OPS,
    DEVICE_NAME_FIELD,
    TIME_BUCKET_FIELD,
    ColumnType,
    DatasetInfo,
    FieldType,
    Filter,
    HistoryScope,
    Metric,
    QueryResult,
    ReportQuery,
    ResultColumn,
)
from repositories.report_data_records_repository import ReportDataRecordRepository
from services.reports.errors import ReportQueryError

_PSEUDO_TYPES: dict[str, ColumnType] = {
    DEVICE_NAME_FIELD: "string",
    COLLECTED_AT_FIELD: "datetime",
    TIME_BUCKET_FIELD: "datetime",
}
_NUMERIC_COMPARISONS = {"gt", "gte", "lt", "lte"}
# A single report query may run this long on PostgreSQL before it is cancelled.
STATEMENT_TIMEOUT_MS = 15_000
_QUERY_CANCELED = "57014"
_LIKE_ESCAPE = "\\"


@dataclass(frozen=True)
class CompiledQuery:
    statement: Select[Any]
    columns: list[ResultColumn]
    limit: int


def compile_query(query: ReportQuery, dataset: DatasetInfo, *, dialect: str) -> CompiledQuery:
    """Validate *query* against *dataset* and build the statement (fetches ``limit + 1`` rows)."""
    return _Compiler(query, dataset, dialect).compile()


def execute_query(db: Session, query: ReportQuery, dataset: DatasetInfo) -> QueryResult:
    dialect = db.get_bind().dialect.name
    compiled = compile_query(query, dataset, dialect=dialect)
    if dialect == "postgresql":
        # Transaction-local, so it cannot leak into other work on this connection.
        db.execute(select(func.set_config("statement_timeout", str(STATEMENT_TIMEOUT_MS), True)))
    try:
        fetched = db.execute(compiled.statement).all()
    except OperationalError as exc:
        if getattr(exc.orig, "sqlstate", None) == _QUERY_CANCELED:
            raise ReportQueryError(
                "The query took too long and was cancelled; narrow the scope, add filters "
                "or group by fewer fields"
            ) from exc
        raise
    truncated = len(fetched) > compiled.limit
    rows = [[_plain(value) for value in row] for row in fetched[: compiled.limit]]
    return QueryResult(columns=compiled.columns, rows=rows, truncated=truncated)


def _plain(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def _bucket_expr(column: ColumnElement[Any], bucket: str, dialect: str) -> ColumnElement[Any]:
    if dialect == "postgresql":
        return func.date_trunc(bucket, column)
    if dialect == "sqlite":
        if bucket == "day":
            return func.date(column)
        return func.date(column, "-6 days", "weekday 1")  # Monday of the week
    raise ReportQueryError(f"time buckets are not supported on {dialect}")


def _escape_like(text: str) -> str:
    return (
        text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )


class _Compiler:
    def __init__(self, query: ReportQuery, dataset: DatasetInfo, dialect: str) -> None:
        self.query = query
        self.dataset = dataset
        self.dialect = dialect
        self.types: dict[str, FieldType] = {f.name: f.type for f in dataset.fields}
        self.bucket = query.scope.bucket if isinstance(query.scope, HistoryScope) else None
        self.with_markers = any(metric.op in DEVICE_METRIC_OPS for metric in query.metrics)
        if self.with_markers:
            self._check_marker_query()
        self.base = self._base_subquery().subquery()

    # -- selectable -------------------------------------------------------------------------

    def _base_subquery(self) -> Select[Any]:
        name = self.query.dataset
        scope = self.query.scope
        if not isinstance(scope, HistoryScope):
            return ReportDataRecordRepository.latest_rows_select(
                name, include_empty=self.with_markers
            )
        stmt = select(ReportDataRecord).where(ReportDataRecord.dataset == name)
        if not self.with_markers:
            stmt = stmt.where(ReportDataRecord.is_empty.is_(False))
        if scope.since is not None:
            stmt = stmt.where(ReportDataRecord.created_at >= scope.since)
        if scope.until is not None:
            stmt = stmt.where(ReportDataRecord.created_at <= scope.until)
        return stmt

    def _check_marker_query(self) -> None:
        """A marker row has no field values, so only device-level questions make sense."""
        allowed = {DEVICE_NAME_FIELD, COLLECTED_AT_FIELD, TIME_BUCKET_FIELD}
        for flt in self.query.filters:
            if flt.field not in allowed:
                raise ReportQueryError(
                    "count_devices / count_items cannot be combined with a filter on "
                    f"{flt.field!r}: devices without items have no field values. "
                    "Filter on device_name or use a device dataset"
                )
        for name in self.query.group_by:
            if name not in allowed:
                raise ReportQueryError(
                    f"count_devices / count_items can only group by device_name or time; "
                    f"not by {name!r}"
                )
        for metric in self.query.metrics:
            if metric.op not in DEVICE_METRIC_OPS and not (
                metric.op == "count" and not metric.field
            ):
                raise ReportQueryError(
                    f"{metric.op!r} cannot be combined with count_devices / count_items; "
                    "run it as a separate query"
                )

    # -- names and types --------------------------------------------------------------------

    def _check_field(self, name: str) -> None:
        if name == TIME_BUCKET_FIELD:
            if self.bucket is None:
                raise ReportQueryError(
                    f"{TIME_BUCKET_FIELD} needs scope 'history' with a bucket (day or week)"
                )
            return
        if name in (DEVICE_NAME_FIELD, COLLECTED_AT_FIELD) or name in self.types:
            return
        raise ReportQueryError(f"unknown field {name!r} in dataset {self.dataset.name!r}")

    def _type(self, name: str) -> FieldType:
        if name == DEVICE_NAME_FIELD:
            return "string"
        return self.types.get(name, "unknown")

    def _column_type(self, name: str) -> ColumnType:
        if name in _PSEUDO_TYPES:
            return _PSEUDO_TYPES[name]
        kind = self._type(name)
        return "mixed" if kind in ("mixed", "unknown") else kind

    # -- expressions ------------------------------------------------------------------------

    def _expr(self, name: str) -> ColumnElement[Any]:
        """The value of *name* as the best-fitting SQL type for its field type."""
        if name == DEVICE_NAME_FIELD:
            return self.base.c.device_name
        if name == COLLECTED_AT_FIELD:
            return self.base.c.created_at
        if name == TIME_BUCKET_FIELD:
            self._check_field(name)  # raises unless a bucket is set
            return _bucket_expr(self.base.c.created_at, self.bucket or "day", self.dialect)
        element = self.base.c.data[name]
        kind = self._type(name)
        if kind == "number":
            return self._guarded(element, "number", element.as_float())
        if kind == "boolean":
            return self._guarded(element, "boolean", element.as_boolean())
        return element.as_string()

    def _guarded(
        self, element: ColumnElement[Any], json_type: str, cast_expr: ColumnElement[Any]
    ) -> ColumnElement[Any]:
        """Cast only values that really have *json_type*; anything else becomes NULL.

        Field types are inferred from a sample, but the query reads every row, and PostgreSQL
        fails the whole statement on ``CAST('N/A' AS FLOAT)``. SQLite casts nothing, so it
        needs no guard.
        """
        if self.dialect != "postgresql":
            return cast_expr
        return case((func.jsonb_typeof(element) == json_type, cast_expr))

    def _json_equals(self, name: str, value: Any) -> ColumnElement[bool]:
        """Compare a mixed-type field to *value* as JSON, so 10, "10" and true stay distinct."""
        encoded = json.dumps(value)
        element = self.base.c.data[name]
        if self.dialect == "postgresql":
            # JSONB's bind type serializes the Python value itself; do not pre-encode it.
            return element == cast(value, JSONB)
        return element == encoded  # SQLite: JSON_QUOTE(...) text

    # -- filters ----------------------------------------------------------------------------

    def _filter(self, flt: Filter) -> ColumnElement[bool]:
        self._check_field(flt.field)
        if flt.field in (TIME_BUCKET_FIELD, COLLECTED_AT_FIELD):
            raise ReportQueryError(
                f"{flt.field!r} cannot be filtered; use the history scope's since/until"
            )
        expr = self._expr(flt.field)
        kind = self._type(flt.field)
        if flt.op == "is_null":
            return expr.is_(None)
        if flt.op == "not_null":
            return expr.is_not(None)
        if flt.op == "contains":
            if kind not in ("string", "mixed", "unknown"):
                raise ReportQueryError(
                    f"'contains' works on text fields only ({flt.field!r} is {kind})"
                )
            pattern = f"%{_escape_like(str(flt.value))}%"
            return self._expr_as_text(flt.field).ilike(pattern, escape=_LIKE_ESCAPE)
        if flt.op in _NUMERIC_COMPARISONS:
            if kind != "number":
                raise ReportQueryError(f"{flt.op!r} needs a number field ({flt.field!r} is {kind})")
            number = self._number(flt.field, flt.value)
            return {
                "gt": expr > number,
                "gte": expr >= number,
                "lt": expr < number,
                "lte": expr <= number,
            }[flt.op]
        if flt.op == "in":
            clauses = [self._equals(flt.field, kind, expr, v) for v in flt.value]
            return or_(*clauses)
        equals = self._equals(flt.field, kind, expr, flt.value)
        if flt.op == "eq":
            return equals
        # ne: a missing value is "not equal" too.
        return or_(~equals, expr.is_(None))

    def _expr_as_text(self, name: str) -> ColumnElement[Any]:
        if name == DEVICE_NAME_FIELD:
            return self.base.c.device_name
        return self.base.c.data[name].as_string()

    def _number(self, name: str, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ReportQueryError(f"value for number field {name!r} must be a number")
        try:
            return float(value)
        except OverflowError as exc:
            raise ReportQueryError(f"value for number field {name!r} is too large") from exc

    def _equals(self, name: str, kind: str, expr: ColumnElement[Any], value: Any) -> Any:
        if name == DEVICE_NAME_FIELD or kind == "string":
            if not isinstance(value, str):
                raise ReportQueryError(f"value for text field {name!r} must be a string")
            return expr == value
        if kind == "number":
            return expr == self._number(name, value)
        if kind == "boolean":
            if not isinstance(value, bool):
                raise ReportQueryError(f"value for boolean field {name!r} must be true or false")
            return expr == value
        return self._json_equals(name, value)

    # -- metrics ----------------------------------------------------------------------------

    def _metric(self, metric: Metric) -> tuple[str, ColumnElement[Any], ColumnType]:
        if metric.op == "count_devices":
            return (
                metric.alias or "count_devices",
                func.count(distinct(self.base.c.device_name)),
                "number",
            )
        if metric.op == "count_items" or (
            metric.op == "count" and not metric.field and self.with_markers
        ):
            items = func.coalesce(func.sum(case((self.base.c.is_empty.is_(True), 0), else_=1)), 0)
            return metric.alias or metric.op, items, "number"
        if metric.op == "count" and not metric.field:
            return metric.alias or "count", func.count(), "number"
        field = metric.field or ""
        self._check_field(field)
        if field in (TIME_BUCKET_FIELD, COLLECTED_AT_FIELD):
            raise ReportQueryError(f"{metric.op!r} cannot use the field {field!r}")
        kind = self._type(field)
        key = metric.alias or f"{metric.op}_{field}"
        expr = self._expr(field)
        if metric.op == "count":
            return key, func.count(expr), "number"
        if metric.op == "count_distinct":
            return key, func.count(distinct(expr)), "number"
        if metric.op == "count_missing":
            return key, func.coalesce(func.sum(case((expr.is_(None), 1), else_=0)), 0), "number"
        if metric.op in ("sum", "avg"):
            if kind != "number":
                raise ReportQueryError(f"{metric.op!r} needs a number field ({field!r} is {kind})")
            return key, getattr(func, metric.op)(expr), "number"
        if kind not in ("number", "string") and field != DEVICE_NAME_FIELD:
            raise ReportQueryError(
                f"{metric.op!r} needs a number or text field ({field!r} is {kind})"
            )
        return key, getattr(func, metric.op)(expr), self._column_type(field)

    # -- assembly ---------------------------------------------------------------------------

    def compile(self) -> CompiledQuery:
        query = self.query
        if query.group_by and not query.metrics:
            raise ReportQueryError("group_by needs at least one metric")
        if query.select and query.metrics:
            raise ReportQueryError("select cannot be combined with metrics; use group_by instead")

        outputs: list[tuple[str, ColumnElement[Any], ColumnType]] = []
        if query.metrics:
            for name in query.group_by:
                self._check_field(name)
                outputs.append((name, self._expr(name), self._column_type(name)))
            outputs.extend(self._metric(metric) for metric in query.metrics)
        else:
            names = query.select or [DEVICE_NAME_FIELD, *self.types]
            for name in names:
                self._check_field(name)
                outputs.append((name, self._expr(name), self._column_type(name)))

        keys = [key for key, _, _ in outputs]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise ReportQueryError(
                f"duplicate output column {sorted(duplicates)[0]!r}; give a metric an alias"
            )
        by_key = {key: expr for key, expr, _ in outputs}

        stmt = select(*(expr.label(key) for key, expr, _ in outputs)).select_from(self.base)
        filters = [self._filter(flt) for flt in query.filters]
        if filters:
            stmt = stmt.where(and_(*filters))
        if query.metrics and query.group_by:
            stmt = stmt.group_by(*(by_key[name] for name in query.group_by))

        orders = []
        for order in query.order_by:
            if order.key not in by_key:
                raise ReportQueryError(f"order_by key {order.key!r} is not an output column")
            column = by_key[order.key]
            orders.append(column.desc() if order.direction == "desc" else column.asc())
        if not orders:
            if query.metrics:
                orders = [by_key[name].asc() for name in query.group_by]
            else:
                orders = [self.base.c.device_name.asc(), self.base.c.id.asc()]
        stmt = stmt.order_by(*orders).limit(query.limit + 1)

        columns = [ResultColumn(key=key, label=key, type=kind) for key, _, kind in outputs]
        return CompiledQuery(statement=stmt, columns=columns, limit=query.limit)


__all__ = ["CompiledQuery", "compile_query", "execute_query"]
