/**
 * Filter kinds the Get from Catalyst Center step understands. Keys match
 * `services/catalyst_center/device_filters.py` on the backend; every kind is a list of
 * values (OR-ed) except `cidr`, which is a single string. Different kinds are AND-ed.
 *
 * The controller matches case-sensitively against the whole value and `.*` is the only
 * wildcard — nothing here translates regex syntax.
 */
export type FilterKey =
  | "hostnames"
  | "management_ips"
  | "cidr"
  | "families"
  | "roles"
  | "software_types"
  | "software_versions"
  | "platform_ids"
  | "serial_numbers"
  | "series"
  | "device_types"
  | "reachability_statuses"
  | "collection_statuses";

export interface FilterKind {
  key: FilterKey;
  label: string;
  /** `cidr` holds one string; every other kind holds a list (one value per line). */
  single: boolean;
  placeholder: string;
  hint: string;
}

export const FILTER_KINDS: readonly FilterKind[] = [
  {
    key: "hostnames",
    label: "Hostname",
    single: false,
    placeholder: "sw.*\n.*-core",
    hint: "Case-sensitive. Use .* as wildcard.",
  },
  {
    key: "management_ips",
    label: "Management IP",
    single: false,
    placeholder: "10.10.20.5\n10.10.20..*",
    hint: "A dot is literal: 10.10.20..* matches 10.10.20.<any>.",
  },
  {
    key: "cidr",
    label: "CIDR",
    single: true,
    placeholder: "10.10.20.0/24",
    hint: "Narrowed on the controller by its IP prefix, then matched exactly.",
  },
  {
    key: "families",
    label: "Family",
    single: false,
    placeholder: "Switches and Hubs",
    hint: "Device family, e.g. Switches and Hubs.",
  },
  {
    key: "roles",
    label: "Role",
    single: false,
    placeholder: "ACCESS\nCORE",
    hint: "Upper case, e.g. ACCESS, CORE, DISTRIBUTION.",
  },
  {
    key: "software_types",
    label: "Software type",
    single: false,
    placeholder: "IOS-XE",
    hint: "e.g. IOS-XE, IOS-XR, NX-OS.",
  },
  {
    key: "software_versions",
    label: "Software version",
    single: false,
    placeholder: "17.12.*",
    hint: "Full match, e.g. 17.12.1 or 17.12.*",
  },
  {
    key: "platform_ids",
    label: "Platform ID",
    single: false,
    placeholder: "C9300-.*",
    hint: "Hardware platform, e.g. C9300-24P.",
  },
  {
    key: "serial_numbers",
    label: "Serial number",
    single: false,
    placeholder: "FOC.*",
    hint: "Case-sensitive.",
  },
  {
    key: "series",
    label: "Series",
    single: false,
    placeholder: ".*Catalyst 9000.*",
    hint: "Device series text.",
  },
  {
    key: "device_types",
    label: "Device type",
    single: false,
    placeholder: ".*9300.*",
    hint: "Device type text.",
  },
  {
    key: "reachability_statuses",
    label: "Reachability",
    single: false,
    placeholder: "Reachable",
    hint: "Reachable or Unreachable.",
  },
  {
    key: "collection_statuses",
    label: "Collection status",
    single: false,
    placeholder: "Managed",
    hint: "Inventory collection state, e.g. Managed.",
  },
];

export const FILTER_KIND_BY_KEY: Readonly<Record<FilterKey, FilterKind>> =
  Object.fromEntries(FILTER_KINDS.map((kind) => [kind.key, kind])) as Record<
    FilterKey,
    FilterKind
  >;

export type FilterValue = string[] | string;
export type FiltersConfig = Partial<Record<FilterKey, FilterValue>>;

const FILTER_KEYS: ReadonlySet<string> = new Set(FILTER_KINDS.map((k) => k.key));

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
        ? value.filter((v): v is string => typeof v === "string")
        : [];
    }
  }
  return result;
}

/** Trimmed, blank-free filters — what is actually sent to preview and counted as "set". */
export function activeFilters(
  filters: FiltersConfig,
): Record<string, string[] | string> {
  const result: Record<string, string[] | string> = {};
  for (const kind of FILTER_KINDS) {
    const value = filters[kind.key];
    if (value === undefined) continue;
    if (typeof value === "string") {
      if (value.trim()) result[kind.key] = value.trim();
    } else {
      const cleaned = value.map((v) => v.trim()).filter(Boolean);
      if (cleaned.length > 0) result[kind.key] = cleaned;
    }
  }
  return result;
}

/** Kinds present in the config, in the canonical display order. */
export function presentKinds(filters: FiltersConfig): FilterKind[] {
  return FILTER_KINDS.filter((kind) => filters[kind.key] !== undefined);
}
