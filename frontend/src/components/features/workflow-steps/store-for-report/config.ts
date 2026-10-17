export type ReportMode = "device" | "items";
export type ReportAggregate = "" | "count";

export const REPORT_MODE_OPTIONS: { value: ReportMode; label: string; hint: string }[] = [
  {
    value: "device",
    label: "One row per device",
    hint: "Facts about the device itself (serial, model, version, counts).",
  },
  {
    value: "items",
    label: "One row per list item",
    hint: "One row for each interface, NTP server, user, … of a list.",
  },
];

export interface ReportField {
  name: string;
  attribute_path: string;
  aggregate: ReportAggregate;
  where_field: string;
  where_equals: string;
}

export const EMPTY_REPORT_FIELD: ReportField = {
  name: "",
  attribute_path: "",
  aggregate: "",
  where_field: "",
  where_equals: "",
};

// Same grammar as backend/services/report_data/report_data_service.py.
const DATASET_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,99}$/;
const FIELD_NAME_RE = /^[a-z][a-z0-9_]{0,63}$/;

/** Message for an invalid dataset name, or null when it is empty (not typed yet) or valid. */
export function datasetNameError(value: string): string | null {
  if (!value.trim() || DATASET_NAME_RE.test(value.trim())) return null;
  return "Use 1–100 lowercase letters, digits, '_' or '-', starting with a letter or digit.";
}

/** Message for an invalid field name, or null when it is empty (not typed yet) or valid. */
export function fieldNameError(value: string): string | null {
  if (!value || FIELD_NAME_RE.test(value)) return null;
  return "Use 1–64 lowercase letters, digits or '_', starting with a letter.";
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function normalizeReportMode(value: unknown): ReportMode {
  return value === "items" ? "items" : "device";
}

/**
 * Coerce a stored `fields` value into well-formed rows (blank rows are kept while editing).
 * Aggregation only exists in device mode, and a `where` only with `count`; anything else is
 * cleared so the config always passes the backend's validation.
 */
export function normalizeReportFields(value: unknown, mode: ReportMode = "device"): ReportField[] {
  if (!Array.isArray(value)) return [];
  return value.map((entry) => {
    const row = typeof entry === "object" && entry !== null ? (entry as Record<string, unknown>) : {};
    const counts = mode === "device" && row.aggregate === "count";
    return {
      name: text(row.name),
      attribute_path: text(row.attribute_path),
      aggregate: counts ? "count" : "",
      where_field: counts ? text(row.where_field) : "",
      where_equals: counts ? text(row.where_equals) : "",
    };
  });
}

/**
 * Re-emit the whole normalized `store-for-report` config, then apply `patch`.
 * Fallbacks mirror `backend/workflow_steps/store_for_report/config.py::get_config()`.
 */
export function buildStoreForReportConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  const merged = { ...config, ...patch };
  const mode = normalizeReportMode(merged.mode);
  return {
    dataset: text(merged.dataset),
    mode,
    items_path: text(merged.items_path),
    fields: normalizeReportFields(merged.fields, mode),
  };
}

/** Replace one row, returning a new array. */
export function updateReportField(
  fields: readonly ReportField[],
  index: number,
  patch: Partial<ReportField>,
): ReportField[] {
  return fields.map((field, i) => (i === index ? { ...field, ...patch } : field));
}

export function removeReportField(fields: readonly ReportField[], index: number): ReportField[] {
  return fields.filter((_, i) => i !== index);
}
