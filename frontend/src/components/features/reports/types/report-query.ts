/** Mirrors backend/models/reports.py. */

export type FieldType = "string" | "number" | "boolean" | "mixed" | "unknown";
export type ColumnType = "string" | "number" | "boolean" | "datetime" | "mixed";
export type FilterOp =
  | "eq"
  | "ne"
  | "in"
  | "contains"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "is_null"
  | "not_null";
export type MetricOp =
  | "count"
  | "count_distinct"
  | "count_missing"
  | "sum"
  | "avg"
  | "min"
  | "max"
  | "count_devices"
  | "count_items";

export interface ReportSource {
  id: string;
  label: string;
}

export interface FieldInfo {
  name: string;
  type: FieldType;
  null_share: number;
  sample_values: string[];
}

export interface DatasetInfo {
  name: string;
  mode: "device" | "items";
  fields: FieldInfo[];
  last_collected_at: string | null;
}

export type FilterValue = string | number | boolean | null | (string | number | boolean)[];

export interface QueryFilter {
  field: string;
  op: FilterOp;
  value?: FilterValue;
}

export interface QueryMetric {
  op: MetricOp;
  field?: string;
  alias?: string;
}

export type QueryScope =
  | { kind: "latest" }
  | { kind: "history"; since?: string; until?: string; bucket?: "day" | "week" };

export interface ReportQuerySpec {
  source: string;
  dataset: string;
  scope: QueryScope;
  filters: QueryFilter[];
  group_by: string[];
  metrics: QueryMetric[];
  select: string[];
  order_by: { key: string; direction: "asc" | "desc" }[];
  limit: number;
}

export interface ResultColumn {
  key: string;
  label: string;
  type: ColumnType;
}

export type CellValue = string | number | boolean | null;

export interface QueryResult {
  columns: ResultColumn[];
  rows: CellValue[][];
  truncated: boolean;
}

/** Pseudo-fields every dataset has (backend/models/reports.py). */
export const DEVICE_NAME_FIELD = "device_name";
export const COLLECTED_AT_FIELD = "collected_at";
export const TIME_BUCKET_FIELD = "time_bucket";
