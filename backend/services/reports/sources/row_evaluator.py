"""Evaluate a ``ReportQuery`` over rows held in memory.

The report database is queried through SQL (``query_compiler.py``). A source that is not a SQL
table (Nautobot) fetches its rows first and lets this module apply the same declarative query:
filters, ``group_by`` + metrics, ``select``, ``order_by`` and ``limit``. The rules mirror the SQL
compiler (``ne`` also matches a missing value, ``contains`` is case-insensitive, a summary
without rows still returns one row, ...); the checks and their messages are the same, so the UI
and the assistant get one set of errors. Only the ``latest`` scope exists: there is no history.

A row is a dict with ``device_name`` plus one key per dataset field; a missing value is ``None``.
Nothing here is mutated: every call builds new lists.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from models.reports import (
    COLLECTED_AT_FIELD,
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
from services.reports.errors import ReportQueryError

Row = dict[str, Any]
_NUMERIC_COMPARISONS = {"gt", "gte", "lt", "lte"}
_TIME_FIELDS = frozenset({TIME_BUCKET_FIELD, COLLECTED_AT_FIELD})
_Aggregate = Callable[[Sequence[Row]], Any]


@dataclass(frozen=True)
class _Output:
    key: str
    kind: ColumnType
    # Plain column: read from a row. Metric: aggregate a group of rows.
    read: Callable[[Row], Any] | None = None
    aggregate: _Aggregate | None = None


@dataclass(frozen=True)
class _Plan:
    outputs: tuple[_Output, ...]
    predicates: tuple[Callable[[Row], bool], ...]
    group_keys: tuple[str, ...]
    order: tuple[tuple[str, bool], ...]  # (output key, descending)
    summary: bool
    limit: int


def validate(query: ReportQuery, dataset: DatasetInfo) -> None:
    """Check *query* against *dataset* without rows (raises ``ReportQueryError``)."""
    _plan(query, dataset)


def evaluate(query: ReportQuery, dataset: DatasetInfo, rows: Sequence[Row]) -> QueryResult:
    """Run *query* over *rows*; fetches nothing, so it is deterministic and cheap to test."""
    plan = _plan(query, dataset)
    kept = [row for row in rows if all(test(row) for test in plan.predicates)]
    table = _summarize(plan, kept) if plan.summary else _list(plan, kept)
    table = _ordered(plan, table)
    columns = [ResultColumn(key=o.key, label=o.key, type=o.kind) for o in plan.outputs]
    return QueryResult(
        columns=columns,
        rows=[list(row) for row in table[: plan.limit]],
        truncated=len(table) > plan.limit,
    )


# -- planning (all validation lives here) -------------------------------------------------------


def _plan(query: ReportQuery, dataset: DatasetInfo) -> _Plan:
    if isinstance(query.scope, HistoryScope):
        raise ReportQueryError(
            "this source holds current data only; use scope 'latest' (it has no history)"
        )
    types: dict[str, FieldType] = {f.name: f.type for f in dataset.fields}
    if query.group_by and not query.metrics:
        raise ReportQueryError("group_by needs at least one metric")
    if query.select and query.metrics:
        raise ReportQueryError("select cannot be combined with metrics; use group_by instead")

    outputs: list[_Output] = []
    if query.metrics:
        outputs.extend(_column(name, types, dataset) for name in query.group_by)
        outputs.extend(_metric(metric, types, dataset) for metric in query.metrics)
    else:
        names = query.select or [DEVICE_NAME_FIELD, *types]
        outputs.extend(_column(name, types, dataset) for name in names)

    keys = [o.key for o in outputs]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ReportQueryError(f"duplicate output column {duplicates[0]!r}; give a metric an alias")
    for order in query.order_by:
        if order.key not in keys:
            raise ReportQueryError(f"order_by key {order.key!r} is not an output column")
    default_order = tuple((name, False) for name in query.group_by)
    order = tuple((o.key, o.direction == "desc") for o in query.order_by) or default_order
    return _Plan(
        outputs=tuple(outputs),
        predicates=tuple(_predicate(flt, types, dataset) for flt in query.filters),
        group_keys=tuple(query.group_by),
        order=order,
        summary=bool(query.metrics),
        limit=query.limit,
    )


def _check_field(name: str, types: dict[str, FieldType], dataset: DatasetInfo) -> None:
    if name in _TIME_FIELDS:
        raise ReportQueryError(
            f"{name!r} is not available: this source holds current data only (no history)"
        )
    if name != DEVICE_NAME_FIELD and name not in types:
        raise ReportQueryError(f"unknown field {name!r} in dataset {dataset.name!r}")


def _kind(name: str, types: dict[str, FieldType]) -> FieldType:
    return "string" if name == DEVICE_NAME_FIELD else types.get(name, "unknown")


def _column_type(name: str, types: dict[str, FieldType]) -> ColumnType:
    kind = _kind(name, types)
    return "mixed" if kind in ("mixed", "unknown") else kind


def _column(name: str, types: dict[str, FieldType], dataset: DatasetInfo) -> _Output:
    _check_field(name, types, dataset)
    return _Output(key=name, kind=_column_type(name, types), read=lambda row: row.get(name))


# -- filters ------------------------------------------------------------------------------------


def _predicate(
    flt: Filter, types: dict[str, FieldType], dataset: DatasetInfo
) -> Callable[[Row], bool]:
    _check_field(flt.field, types, dataset)
    name, kind = flt.field, _kind(flt.field, types)
    if flt.op == "is_null":
        return lambda row: row.get(name) is None
    if flt.op == "not_null":
        return lambda row: row.get(name) is not None
    if flt.op == "contains":
        if kind not in ("string", "mixed", "unknown"):
            raise ReportQueryError(f"'contains' works on text fields only ({name!r} is {kind})")
        needle = str(flt.value).lower()
        return lambda row: row.get(name) is not None and needle in str(row[name]).lower()
    if flt.op in _NUMERIC_COMPARISONS:
        if kind != "number":
            raise ReportQueryError(f"{flt.op!r} needs a number field ({name!r} is {kind})")
        number = _number(name, flt.value)
        compare = {
            "gt": lambda a: a > number,
            "gte": lambda a: a >= number,
            "lt": lambda a: a < number,
            "lte": lambda a: a <= number,
        }[flt.op]
        return lambda row: row.get(name) is not None and compare(row[name])
    if flt.op == "in":
        wanted = [_comparable(name, kind, v) for v in flt.value]
        return lambda row: row.get(name) is not None and row[name] in wanted
    wanted_one = _comparable(name, kind, flt.value)
    if flt.op == "eq":
        return lambda row: row.get(name) is not None and row[name] == wanted_one
    # ne: a missing value is "not equal" too.
    return lambda row: row.get(name) is None or row[name] != wanted_one


def _number(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReportQueryError(f"value for number field {name!r} must be a number")
    return float(value)


def _comparable(name: str, kind: str, value: Any) -> Any:
    """The filter value checked and shaped like the stored values of the field."""
    if kind == "string":
        if not isinstance(value, str):
            raise ReportQueryError(f"value for text field {name!r} must be a string")
        return value
    if kind == "number":
        return _number(name, value)
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ReportQueryError(f"value for boolean field {name!r} must be true or false")
        return value
    return value


# -- metrics ------------------------------------------------------------------------------------


def _metric(metric: Metric, types: dict[str, FieldType], dataset: DatasetInfo) -> _Output:
    if metric.op in ("count_devices", "count_items"):
        distinct_devices = metric.op == "count_devices"
        return _Output(
            key=metric.alias or metric.op,
            kind="number",
            aggregate=(
                (lambda rows: len({r.get(DEVICE_NAME_FIELD) for r in rows}))
                if distinct_devices
                else len
            ),
        )
    if metric.op == "count" and not metric.field:
        return _Output(key=metric.alias or "count", kind="number", aggregate=len)
    field = metric.field or ""
    _check_field(field, types, dataset)
    kind = _kind(field, types)
    key = metric.alias or f"{metric.op}_{field}"

    def values(rows: Sequence[Row]) -> list[Any]:
        return [r[field] for r in rows if r.get(field) is not None]

    if metric.op == "count":
        return _Output(key=key, kind="number", aggregate=lambda rows: len(values(rows)))
    if metric.op == "count_distinct":
        return _Output(key=key, kind="number", aggregate=lambda rows: len(set(values(rows))))
    if metric.op == "count_missing":
        return _Output(key=key, kind="number", aggregate=lambda rows: len(rows) - len(values(rows)))
    if metric.op in ("sum", "avg"):
        if kind != "number":
            raise ReportQueryError(f"{metric.op!r} needs a number field ({field!r} is {kind})")
        return _Output(key=key, kind="number", aggregate=_numeric(metric.op, values))
    if kind not in ("number", "string"):
        raise ReportQueryError(f"{metric.op!r} needs a number or text field ({field!r} is {kind})")
    pick = min if metric.op == "min" else max
    return _Output(
        key=key,
        kind=_column_type(field, types),
        aggregate=lambda rows: pick(found) if (found := values(rows)) else None,
    )


def _numeric(op: str, values: Callable[[Sequence[Row]], list[Any]]) -> _Aggregate:
    def aggregate(rows: Sequence[Row]) -> Any:
        found = values(rows)
        if not found:
            return None
        return sum(found) if op == "sum" else sum(found) / len(found)

    return aggregate


# -- assembly -----------------------------------------------------------------------------------


def _list(plan: _Plan, rows: Sequence[Row]) -> list[tuple[Any, ...]]:
    # The default order is the device name; the sort is stable, so equal names keep their order.
    by_name = sorted(rows, key=lambda r: _nulls_last(r.get(DEVICE_NAME_FIELD)))
    return [tuple(o.read(row) for o in plan.outputs if o.read) for row in by_name]


def _summarize(plan: _Plan, rows: Sequence[Row]) -> list[tuple[Any, ...]]:
    groups: dict[tuple[Any, ...], list[Row]] = {}
    for row in rows:
        groups.setdefault(tuple(row.get(k) for k in plan.group_keys), []).append(row)
    if not plan.group_keys:
        groups = {(): list(rows)}  # SQL: an aggregate without GROUP BY always yields one row
    table = []
    for key, members in groups.items():
        by_name = dict(zip(plan.group_keys, key, strict=True))
        table.append(
            tuple(
                by_name[o.key] if o.aggregate is None else o.aggregate(members)
                for o in plan.outputs
            )
        )
    return table


def _ordered(plan: _Plan, table: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    if not plan.summary and not plan.order:
        return table
    index = {o.key: i for i, o in enumerate(plan.outputs)}
    result = list(table)
    # Stable sorts from the least to the most significant key. Missing values sort as PostgreSQL
    # does (the SQL compiler's database): last when ascending, first when descending.
    for key, descending in reversed(plan.order):
        position = index[key]
        present = [r for r in result if r[position] is not None]
        missing = [r for r in result if r[position] is None]
        present.sort(key=lambda r, p=position: r[p], reverse=descending)
        result = missing + present if descending else present + missing
    return result


def _nulls_last(value: Any) -> tuple[bool, Any]:
    return (value is None, "" if value is None else value)
