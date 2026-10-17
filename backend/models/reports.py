"""Request/response models for the Reports query API (doc/REPORTS.md)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FieldType = Literal["string", "number", "boolean", "mixed", "unknown"]
ColumnType = Literal["string", "number", "boolean", "datetime", "mixed"]
FilterOp = Literal["eq", "ne", "in", "contains", "gt", "gte", "lt", "lte", "is_null", "not_null"]
MetricOp = Literal[
    "count",
    "count_distinct",
    "count_missing",
    "sum",
    "avg",
    "min",
    "max",
    "count_devices",
    "count_items",
]
# Take no field. The last two read the empty-collection markers too, so a device whose list was
# empty still counts as a device (and as zero items).
DEVICE_METRIC_OPS = frozenset({"count_devices", "count_items"})

MAX_QUERY_LIMIT = 5000
DEFAULT_QUERY_LIMIT = 500
MAX_IN_VALUES = 100
# Filter numbers must be exactly representable and finite (JSON has no NaN/Infinity).
MAX_FILTER_NUMBER = 10**15

# Pseudo-fields every dataset has. Dataset fields may not use these names.
DEVICE_NAME_FIELD = "device_name"
COLLECTED_AT_FIELD = "collected_at"
TIME_BUCKET_FIELD = "time_bucket"
RESERVED_FIELD_NAMES = frozenset({DEVICE_NAME_FIELD, COLLECTED_AT_FIELD, TIME_BUCKET_FIELD})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -- catalog ------------------------------------------------------------------------------------


class FieldInfo(_Strict):
    name: str
    type: FieldType
    # Fraction of sampled rows where the field is null or missing.
    null_share: float
    # A few distinct example values for the UI. Never sent to the AI assistant.
    sample_values: list[str]


class DatasetInfo(_Strict):
    name: str
    mode: Literal["device", "items"]
    fields: list[FieldInfo]
    last_collected_at: datetime | None = None


class SourceInfo(_Strict):
    id: str
    label: str


# -- query --------------------------------------------------------------------------------------


class LatestScope(_Strict):
    kind: Literal["latest"] = "latest"


class HistoryScope(_Strict):
    kind: Literal["history"] = "history"
    since: datetime | None = None
    until: datetime | None = None
    bucket: Literal["day", "week"] | None = None


Scope = Annotated[LatestScope | HistoryScope, Field(discriminator="kind")]


class Filter(_Strict):
    field: str = Field(min_length=1, max_length=64)
    op: FilterOp
    value: Any = None

    @model_validator(mode="after")
    def _value_matches_op(self) -> Filter:
        if self.op in ("is_null", "not_null"):
            return self
        if self.op == "in":
            if not isinstance(self.value, list) or not 1 <= len(self.value) <= MAX_IN_VALUES:
                raise ValueError(f"'in' needs a list of 1-{MAX_IN_VALUES} values")
            if not all(_is_filter_value(v) for v in self.value):
                raise ValueError(
                    "'in' values must be strings, booleans or finite numbers of reasonable size"
                )
            return self
        if not _is_filter_value(self.value):
            raise ValueError(
                f"'{self.op}' needs a string, boolean or finite number of reasonable size"
            )
        return self


class Metric(_Strict):
    op: MetricOp
    field: str | None = Field(default=None, max_length=64)
    alias: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")

    @model_validator(mode="after")
    def _field_matches_op(self) -> Metric:
        if self.op in DEVICE_METRIC_OPS:
            if self.field:
                raise ValueError(f"'{self.op}' takes no field")
            return self
        if self.op == "count":
            return self
        if not self.field:
            raise ValueError(f"'{self.op}' needs a field")
        return self


class OrderBy(_Strict):
    key: str = Field(min_length=1, max_length=64)
    direction: Literal["asc", "desc"] = "asc"


class ReportQuery(_Strict):
    source: str = Field(default="report_data", min_length=1, max_length=64)
    dataset: str = Field(min_length=1, max_length=100)
    scope: Scope = Field(default_factory=LatestScope)
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    group_by: list[str] = Field(default_factory=list, max_length=3)
    metrics: list[Metric] = Field(default_factory=list, max_length=10)
    # List mode (no metrics): the columns to return. Empty means device name plus all fields.
    select: list[str] = Field(default_factory=list, max_length=50)
    order_by: list[OrderBy] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT)


class ResultColumn(_Strict):
    key: str
    label: str
    type: ColumnType


class QueryResult(_Strict):
    columns: list[ResultColumn]
    rows: list[list[Any]]
    # More rows matched than the limit allowed.
    truncated: bool = False


def _is_filter_value(value: Any) -> bool:
    if isinstance(value, bool) or isinstance(value, str):
        return True
    if isinstance(value, int):
        return abs(value) <= MAX_FILTER_NUMBER
    if isinstance(value, float):
        return math.isfinite(value) and abs(value) <= MAX_FILTER_NUMBER
    return False
