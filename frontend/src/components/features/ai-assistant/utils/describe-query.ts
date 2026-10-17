import type { ReportQuerySpec } from "@/components/features/reports/types/report-query";
import {
  FILTER_OP_LABELS,
  METRIC_OP_LABELS,
  metricTakesField,
} from "@/components/features/reports/utils/query-spec";

function describeScope(scope: ReportQuerySpec["scope"]): string {
  if (scope.kind === "latest") return "Scope: latest collection per device";
  const parts = ["Scope: history"];
  if (scope.since) parts.push(`from ${scope.since}`);
  if (scope.until) parts.push(`until ${scope.until}`);
  const text = parts.join(" ");
  return scope.bucket ? `${text}, per ${scope.bucket}` : text;
}

/** One readable line per part of a query, for a proposal card. */
export function describeQuery(query: ReportQuerySpec): string[] {
  const lines = [`Dataset: ${query.dataset}`, describeScope(query.scope)];
  for (const filter of query.filters) {
    const value = Array.isArray(filter.value) ? filter.value.join(", ") : filter.value;
    const tail = value === undefined || value === null ? "" : ` ${String(value)}`;
    lines.push(`Filter: ${filter.field} ${FILTER_OP_LABELS[filter.op]}${tail}`);
  }
  if (query.group_by.length > 0) lines.push(`Group by: ${query.group_by.join(", ")}`);
  for (const metric of query.metrics) {
    const label = METRIC_OP_LABELS[metric.op];
    const subject = metric.field ? ` of ${metric.field}` : "";
    const alias = metric.alias ? ` as ${metric.alias}` : "";
    // "Count rows" already says what it counts; fields apply to the other operations.
    lines.push(`Metric: ${label}${metricTakesField(metric.op) ? subject : ""}${alias}`);
  }
  if (query.metrics.length === 0) {
    lines.push(
      query.select.length > 0 ? `Columns: ${query.select.join(", ")}` : "Shows all columns",
    );
  }
  for (const order of query.order_by) {
    lines.push(
      `Order by: ${order.key}${order.direction === "desc" ? " (descending)" : ""}`,
    );
  }
  lines.push(`Limit: ${query.limit}`);
  return lines;
}
