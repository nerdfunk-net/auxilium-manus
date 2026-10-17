import type {
  CellValue,
  FilterValue,
  QueryResult,
  ReportQuerySpec,
} from "../types/report-query";
import { DEFAULT_BUILDER_STATE, type BuilderState } from "./query-spec";

function filterValueText(value: FilterValue | undefined): string {
  if (value === undefined || value === null) return "";
  return Array.isArray(value) ? value.join(", ") : String(value);
}

/** Inverse of `buildReportQuery`: fill the query builder from a saved query. */
export function queryToBuilderState(query: ReportQuerySpec): BuilderState {
  const scope = query.scope;
  const order = query.order_by[0];
  return {
    ...DEFAULT_BUILDER_STATE,
    sourceId: query.source,
    dataset: query.dataset,
    scopeKind: scope.kind,
    since: scope.kind === "history" ? toLocalInput(scope.since) : "",
    until: scope.kind === "history" ? toLocalInput(scope.until) : "",
    bucket: scope.kind === "history" ? (scope.bucket ?? "") : "",
    mode: query.metrics.length > 0 ? "summary" : "rows",
    select: query.select,
    groupBy: query.group_by,
    metrics: query.metrics.map((m) => ({ op: m.op, field: m.field ?? "", alias: m.alias ?? "" })),
    filters: query.filters.map((f) => ({ field: f.field, op: f.op, value: filterValueText(f.value) })),
    orderKey: order?.key ?? "",
    orderDirection: order?.direction ?? "asc",
    limit: String(query.limit),
  };
}

/** ISO timestamp -> the "YYYY-MM-DDTHH:mm" text a datetime-local input holds (local time). */
function toLocalInput(iso: string | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export interface ChartData {
  labelKey: string;
  seriesKeys: string[];
  points: Record<string, CellValue>[];
}

/** First column labels the points; every numeric column is a series. */
export function chartData(result: QueryResult): ChartData {
  const [first, ...rest] = result.columns;
  const labelKey = first?.key ?? "";
  const seriesKeys = rest.filter((c) => c.type === "number").map((c) => c.key);
  const points = result.rows.map((row) =>
    Object.fromEntries(result.columns.map((column, index) => [column.key, row[index] ?? null])),
  );
  return { labelKey, seriesKeys, points };
}

/** The value shown by a "single number" section: first numeric cell of the first row. */
export function singleNumber(result: QueryResult): { label: string; value: number } | null {
  const row = result.rows[0];
  if (!row) return null;
  const index = result.columns.findIndex(
    (column, i) => column.type === "number" && typeof row[i] === "number",
  );
  if (index < 0) return null;
  return { label: result.columns[index].label, value: row[index] as number };
}

/** A new array with the item moved by `delta`; the same array when the move is out of range. */
export function moveSection<T>(items: readonly T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= items.length) return items as T[];
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/** `section-N` with the smallest N not used yet (ids must match the backend pattern). */
export function newSectionId(existing: readonly string[]): string {
  let n = existing.length + 1;
  while (existing.includes(`section-${n}`)) n += 1;
  return `section-${n}`;
}
