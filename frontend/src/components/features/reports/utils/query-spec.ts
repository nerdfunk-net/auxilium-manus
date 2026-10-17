import {
  COLLECTED_AT_FIELD,
  DEVICE_NAME_FIELD,
  TIME_BUCKET_FIELD,
  type CellValue,
  type DatasetInfo,
  type FieldType,
  type FilterOp,
  type FilterValue,
  type MetricOp,
  type QueryFilter,
  type QueryMetric,
  type QueryScope,
  type ReportQuerySpec,
} from "../types/report-query";

export const MAX_QUERY_LIMIT = 5000;
/** Same rule as the backend (`Metric.alias`): the name of a metric's result column. */
export const METRIC_ALIAS_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
export const DEFAULT_QUERY_LIMIT = 500;

export interface BuilderFilter {
  field: string;
  op: FilterOp;
  value: string;
}

export interface BuilderMetric {
  op: MetricOp;
  field: string;
  alias: string;
}

/** Everything the query builder form holds; converted to a ReportQuerySpec on run. */
export interface BuilderState {
  sourceId: string;
  dataset: string;
  scopeKind: "latest" | "history";
  since: string;
  until: string;
  bucket: "" | "day" | "week";
  mode: "rows" | "summary";
  select: string[];
  groupBy: string[];
  metrics: BuilderMetric[];
  filters: BuilderFilter[];
  orderKey: string;
  orderDirection: "asc" | "desc";
  /** Kept as typed text so the input can be emptied; parsed when the query is built. */
  limit: string;
}

export const DEFAULT_BUILDER_STATE: BuilderState = {
  sourceId: "",
  dataset: "",
  scopeKind: "latest",
  since: "",
  until: "",
  bucket: "",
  mode: "rows",
  select: [],
  groupBy: [],
  metrics: [],
  filters: [],
  orderKey: "",
  orderDirection: "asc",
  limit: String(DEFAULT_QUERY_LIMIT),
};

export interface FieldChoice {
  name: string;
  type: FieldType;
}

export type BuildResult =
  | { ok: true; query: ReportQuerySpec }
  | { ok: false; errors: string[] };

const NULL_OPS: readonly FilterOp[] = ["is_null", "not_null"];

export const FILTER_OP_LABELS: Record<FilterOp, string> = {
  eq: "equals",
  ne: "does not equal",
  in: "is one of",
  contains: "contains",
  gt: "greater than",
  gte: "greater or equal",
  lt: "less than",
  lte: "less or equal",
  is_null: "is empty",
  not_null: "is not empty",
};

export const METRIC_OP_LABELS: Record<MetricOp, string> = {
  count: "Count rows",
  count_distinct: "Count distinct values",
  count_missing: "Count empty values",
  sum: "Sum",
  avg: "Average",
  min: "Minimum",
  max: "Maximum",
  count_devices: "Count devices (including those with no items)",
  count_items: "Count items (0 for devices with no items)",
};

/** Operations that take no field. The last two also see devices whose list was empty. */
export const DEVICE_METRIC_OPS: readonly MetricOp[] = ["count_devices", "count_items"];

export function metricTakesField(op: MetricOp): boolean {
  return op !== "count" && !DEVICE_METRIC_OPS.includes(op);
}

export function operatorsForType(type: FieldType): FilterOp[] {
  const ops: FilterOp[] = ["eq", "ne", "in"];
  if (type === "string" || type === "mixed" || type === "unknown") ops.push("contains");
  if (type === "number") ops.push("gt", "gte", "lt", "lte");
  ops.push("is_null", "not_null");
  return ops;
}

/** device_name first (every dataset has it), then the dataset's own fields. */
export function fieldChoices(dataset: DatasetInfo | undefined): FieldChoice[] {
  const own = (dataset?.fields ?? []).map((f) => ({ name: f.name, type: f.type }));
  return [{ name: DEVICE_NAME_FIELD, type: "string" }, ...own];
}

/** Columns a list query can return: every field plus the collection time. */
export function columnOptions(dataset: DatasetInfo | undefined): string[] {
  return [...fieldChoices(dataset).map((f) => f.name), COLLECTED_AT_FIELD];
}

/** What a summary may group by; time_bucket only exists in a bucketed history scope. */
export function groupByOptions(state: BuilderState, dataset: DatasetInfo | undefined): string[] {
  const names = fieldChoices(dataset).map((f) => f.name);
  return state.scopeKind === "history" && state.bucket ? [TIME_BUCKET_FIELD, ...names] : names;
}

export function metricFieldChoices(op: MetricOp, dataset: DatasetInfo | undefined): FieldChoice[] {
  if (DEVICE_METRIC_OPS.includes(op)) return [];
  const all = fieldChoices(dataset);
  if (op === "sum" || op === "avg") return all.filter((f) => f.type === "number");
  if (op === "min" || op === "max") {
    return all.filter((f) => f.type === "number" || f.type === "string");
  }
  return all;
}

function guessScalar(raw: string): string | number | boolean {
  const text = raw.trim();
  if (text === "true") return true;
  if (text === "false") return false;
  if (text !== "" && Number.isFinite(Number(text))) return Number(text);
  return raw;
}

function coerceScalar(type: FieldType, raw: string): string | number | boolean {
  if (type === "number") {
    const text = raw.trim();
    if (text === "" || !Number.isFinite(Number(text))) {
      throw new Error(`"${raw.trim()}" is not a number`);
    }
    return Number(text);
  }
  if (type === "boolean") {
    const text = raw.trim().toLowerCase();
    if (text !== "true" && text !== "false") throw new Error("use true or false");
    return text === "true";
  }
  if (type === "string") return raw;
  return guessScalar(raw);
}

/** Convert the text typed into a filter row to the JSON value the API expects. */
export function coerceFilterValue(
  op: FilterOp,
  type: FieldType,
  raw: string,
): FilterValue | undefined {
  if (NULL_OPS.includes(op)) return undefined;
  if (op === "in") {
    const parts = raw
      .split(",")
      .map((part) => part.trim())
      .filter((part) => part !== "");
    if (parts.length === 0) throw new Error("enter at least one value");
    return parts.map((part) => coerceScalar(type, part));
  }
  if (raw.trim() === "") throw new Error("enter a value");
  if (op === "contains") return raw;
  return coerceScalar(type, raw);
}

function buildScope(state: BuilderState): QueryScope {
  if (state.scopeKind === "latest") return { kind: "latest" };
  const scope: QueryScope = { kind: "history" };
  if (state.since) scope.since = new Date(state.since).toISOString();
  if (state.until) scope.until = new Date(state.until).toISOString();
  if (state.bucket) scope.bucket = state.bucket;
  return scope;
}

function buildFilters(
  state: BuilderState,
  choices: FieldChoice[],
  errors: string[],
): QueryFilter[] {
  const filters: QueryFilter[] = [];
  for (const row of state.filters) {
    const field = choices.find((c) => c.name === row.field);
    if (!field) {
      errors.push(`Filter: choose a field`);
      continue;
    }
    try {
      const value = coerceFilterValue(row.op, field.type, row.value);
      filters.push(value === undefined ? { field: row.field, op: row.op } : { field: row.field, op: row.op, value });
    } catch (error) {
      errors.push(`Filter on ${row.field}: ${error instanceof Error ? error.message : "invalid value"}`);
    }
  }
  return filters;
}

function buildMetrics(state: BuilderState, errors: string[]): QueryMetric[] {
  if (state.metrics.length === 0) errors.push("Add at least one metric to summarize.");
  const metrics: QueryMetric[] = [];
  for (const row of state.metrics) {
    if (metricTakesField(row.op) && !row.field) {
      errors.push(`${METRIC_OP_LABELS[row.op]}: choose a field`);
      continue;
    }
    const alias = row.alias.trim();
    if (alias && !METRIC_ALIAS_PATTERN.test(alias)) {
      errors.push(
        `Column name "${alias}": use lowercase letters, digits and underscores, starting with a letter (max 64 characters).`,
      );
      continue;
    }
    const metric: QueryMetric = { op: row.op };
    if (row.field && row.op !== "count_devices" && row.op !== "count_items") {
      metric.field = row.field;
    }
    if (row.alias.trim()) metric.alias = row.alias.trim();
    metrics.push(metric);
  }
  return metrics;
}

/**
 * Drop choices that no longer make sense after something else changed (another mode, scope,
 * bucket, column selection, metric or field), so the form never sends a query the backend
 * would reject for a reason the user cannot see.
 */
export function normalizeBuilderState(
  state: BuilderState,
  dataset: DatasetInfo | undefined,
): BuilderState {
  const choices = fieldChoices(dataset);
  const columns = columnOptions(dataset);
  const groups = groupByOptions(state, dataset);

  const filters = state.filters.map((row) => {
    const field = choices.find((c) => c.name === row.field);
    if (!field || operatorsForType(field.type).includes(row.op)) return row;
    return { ...row, op: "eq" as FilterOp, value: "" };
  });
  const metrics = state.metrics.map((row) =>
    row.field && !metricFieldChoices(row.op, dataset).some((c) => c.name === row.field)
      ? { ...row, field: "" }
      : row,
  );
  const next: BuilderState = {
    ...state,
    filters,
    metrics,
    select: state.select.filter((name) => columns.includes(name)),
    groupBy: state.groupBy.filter((name) => groups.includes(name)),
  };
  return outputKeys(next, dataset).includes(next.orderKey) ? next : { ...next, orderKey: "" };
}

function parseLimit(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isInteger(value) && value >= 1 && value <= MAX_QUERY_LIMIT ? value : null;
}

/** Validate the form state and produce the API query, or readable errors. */
export function buildReportQuery(
  rawState: BuilderState,
  dataset: DatasetInfo | undefined,
): BuildResult {
  const state = normalizeBuilderState(rawState, dataset);
  const errors: string[] = [];
  if (!state.sourceId) errors.push("Choose a source.");
  if (!state.dataset) errors.push("Choose a dataset.");
  const limit = parseLimit(state.limit);
  if (limit === null) errors.push(`Limit must be a whole number from 1 to ${MAX_QUERY_LIMIT}.`);

  const filters = buildFilters(state, fieldChoices(dataset), errors);
  const summary = state.mode === "summary";
  const metrics = summary ? buildMetrics(state, errors) : [];
  if (errors.length > 0) return { ok: false, errors };

  return {
    ok: true,
    query: {
      source: state.sourceId,
      dataset: state.dataset,
      scope: buildScope(state),
      filters,
      group_by: summary ? state.groupBy : [],
      metrics,
      select: summary ? [] : state.select,
      order_by: state.orderKey ? [{ key: state.orderKey, direction: state.orderDirection }] : [],
      limit: limit ?? DEFAULT_QUERY_LIMIT,
    },
  };
}

/** The key backend/services/reports/query_compiler.py gives a metric's output column. */
export function metricKey(metric: BuilderMetric): string {
  const alias = metric.alias.trim();
  if (alias) return alias;
  if (DEVICE_METRIC_OPS.includes(metric.op)) return metric.op;
  return metric.op === "count" && !metric.field ? "count" : `${metric.op}_${metric.field}`;
}

/** Columns the current query will return, i.e. what the result can be ordered by. */
export function outputKeys(state: BuilderState, dataset: DatasetInfo | undefined): string[] {
  if (state.mode === "summary") {
    return [...state.groupBy, ...state.metrics.map(metricKey)];
  }
  if (state.select.length > 0) return state.select;
  return fieldChoices(dataset).map((field) => field.name);
}

/** Display text for one result cell. */
export function formatCell(value: CellValue): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}
