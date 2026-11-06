/**
 * Filter kinds the Get from ACI step understands. Keys match
 * `services/aci/device_filters.py` on the backend; every kind is a list of values (OR-ed)
 * except `cidr`, which is a single string. Different kinds are AND-ed.
 *
 * Text matching is case-sensitive against the whole value; `*` (any text) and `?` (one
 * character) are the only wildcards, every other character is literal. All of it runs on the
 * backend - nothing here translates wildcard or regex syntax.
 */
export type FilterKey =
  | "names"
  | "roles"
  | "pod_ids"
  | "node_ids"
  | "models"
  | "serials"
  | "versions"
  | "fabric_states"
  | "cidr";

export interface FilterKind {
  key: FilterKey;
  label: string;
  /** `cidr` holds one string; every other kind holds a list (one value per line). */
  single: boolean;
  placeholder: string;
  hint: string;
  /** A closed set of values: shown as checkboxes instead of a text area. */
  options?: readonly string[];
  /** Whole numbers: digit-only lines are sent as numbers. */
  numeric?: boolean;
}

export const FILTER_KINDS: readonly FilterKind[] = [
  {
    key: "names",
    label: "Name",
    single: false,
    placeholder: "dc1-leaf-*\nspine-?",
    hint: "Node name, case-sensitive. * = any text, ? = one character.",
  },
  {
    key: "roles",
    label: "Role",
    single: false,
    placeholder: "",
    hint: "An unticked row is not a filter. Both roles are taken only together with another filter or allow_all. APIC controllers are never selected.",
    options: ["leaf", "spine"],
  },
  {
    key: "pod_ids",
    label: "Pod",
    single: false,
    placeholder: "1\n2",
    hint: "Pod number, whole numbers only.",
    numeric: true,
  },
  {
    key: "node_ids",
    label: "Node ID",
    single: false,
    placeholder: "101\n102",
    hint: "Fabric node ID, whole numbers only.",
    numeric: true,
  },
  {
    key: "models",
    label: "Model",
    single: false,
    placeholder: "N9K-C93*",
    hint: "Hardware model, e.g. N9K-C9336C-FX2.",
  },
  {
    key: "serials",
    label: "Serial number",
    single: false,
    placeholder: "FDO*",
    hint: "Case-sensitive.",
  },
  {
    key: "versions",
    label: "Software version",
    single: false,
    placeholder: "n9000-16.1*",
    hint: "As the APIC reports it, e.g. n9000-16.1(4h).",
  },
  {
    key: "fabric_states",
    label: "Fabric state",
    single: false,
    placeholder: "active",
    hint: "e.g. active, inactive, discovering.",
  },
  {
    key: "cidr",
    label: "CIDR",
    single: true,
    placeholder: "10.1.1.0/24",
    hint: "Matched against the management IP (out-of-band, else in-band). A switch without one never matches.",
  },
];

export const FILTER_KIND_BY_KEY: Readonly<Record<FilterKey, FilterKind>> =
  Object.fromEntries(FILTER_KINDS.map((kind) => [kind.key, kind])) as Record<
    FilterKey,
    FilterKind
  >;

export type FilterValue = string[] | string;
export type FiltersConfig = Partial<Record<FilterKey, FilterValue>>;

/** What is sent to the preview endpoint (and what a run receives once cleaned). */
export type ActiveFilters = Record<string, string | Array<string | number>>;

const FILTER_KEYS: ReadonlySet<string> = new Set(FILTER_KINDS.map((k) => k.key));
const DIGITS_ONLY = /^\d+$/;

/**
 * One element of a stored list as the text the textarea edits. Text always stays (the backend names
 * a bad value). A whole number is kept for the id filters, because the backend and the registry's
 * own example store `[101]` as well as `["101"]`; anything else cannot be a value of the list.
 */
function listItemText(kind: FilterKind, value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (kind.numeric && typeof value === "number" && Number.isInteger(value)) {
    return [String(value)];
  }
  return [];
}

/** Reads `config.filters`, dropping unknown keys and values of the wrong shape. */
export function filtersFromConfig(config: Record<string, unknown>): FiltersConfig {
  const raw = config.filters;
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return {};
  }
  const result: FiltersConfig = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!FILTER_KEYS.has(key)) continue;
    const kind = FILTER_KIND_BY_KEY[key as FilterKey];
    if (kind.single) {
      result[kind.key] = typeof value === "string" ? value : "";
    } else {
      result[kind.key] = Array.isArray(value)
        ? value.flatMap((item) => listItemText(kind, item))
        : [];
    }
  }
  return result;
}

/** Trimmed, blank-free filters - what is actually sent to preview and counted as "set". */
export function activeFilters(filters: FiltersConfig): ActiveFilters {
  const result: ActiveFilters = {};
  for (const kind of FILTER_KINDS) {
    const value = filters[kind.key];
    if (value === undefined) continue;
    if (typeof value === "string") {
      if (value.trim()) result[kind.key] = value.trim();
      continue;
    }
    const cleaned = value.map((v) => v.trim()).filter(Boolean);
    if (cleaned.length === 0) continue;
    // A line that is not a whole number stays text, so the backend names the problem.
    result[kind.key] = kind.numeric
      ? cleaned.map((v) => (DIGITS_ONLY.test(v) ? Number(v) : v))
      : cleaned;
  }
  return result;
}

/** Kinds present in the config, in the canonical display order. */
export function presentKinds(filters: FiltersConfig): FilterKind[] {
  return FILTER_KINDS.filter((kind) => filters[kind.key] !== undefined);
}

/**
 * Adds or removes one option of a closed set. Known options keep their canonical order;
 * values outside the set (from an edited config) are kept after them, never dropped silently.
 */
export function toggleOption(
  values: readonly string[],
  option: string,
  order: readonly string[],
): string[] {
  const next = values.includes(option)
    ? values.filter((value) => value !== option)
    : [...values, option];
  const known = order.filter((candidate) => next.includes(candidate));
  const unknown = next.filter((value) => !order.includes(value));
  return [...known, ...unknown];
}
