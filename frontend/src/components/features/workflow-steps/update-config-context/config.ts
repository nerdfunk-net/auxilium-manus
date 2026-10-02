export type UpdateConfigContextMode = "write" | "update" | "append";
export type ValueSourceType = "attribute" | "template";
export type DeviceIdentifierMode = "from_context" | "explicit";

export interface ValueSourceConfig {
  type: ValueSourceType;
  attribute_path: string;
  template_id: number | null;
}

export interface DeviceIdentifierConfig {
  mode: DeviceIdentifierMode;
  id: string;
  name: string;
}

/** One path/value pair of an `update` mode step. */
export interface UpdateEntry {
  path: string;
  value_source: ValueSourceConfig;
}

export interface UpdateConfigContextConfig {
  mode: UpdateConfigContextMode;
  /** write/append only — update mode uses `updates`. */
  path: string;
  /** update mode only: path/value pairs applied together in a single PATCH (always at least one). */
  updates: UpdateEntry[];
  /** update/append with a path: copy the path's top-level key from the global config context when the device has no local copy. */
  create_local_if_missing: boolean;
  /** write/append only — update mode uses `updates[].value_source`. */
  value_source: ValueSourceConfig;
  device_identifier: DeviceIdentifierConfig;
}

export function emptyValueSource(): ValueSourceConfig {
  return { type: "attribute", attribute_path: "", template_id: null };
}

export function emptyUpdateEntry(): UpdateEntry {
  return { path: "", value_source: emptyValueSource() };
}

export const DEFAULT_UPDATE_CONFIG_CONTEXT_CONFIG: UpdateConfigContextConfig = {
  mode: "write",
  path: "",
  updates: [emptyUpdateEntry()],
  create_local_if_missing: false,
  value_source: emptyValueSource(),
  device_identifier: { mode: "from_context", id: "", name: "" },
};

const CONFIG_CONTEXT_ATTRIBUTE_PREFIXES = [
  "nautobot.config_context",
  "nautobot.local_config_context_data",
] as const;

/**
 * The attribute picker returns workflow attribute paths, but `path` is
 * relative to the device's local config context. Strip the attribute prefix
 * (`nautobot.config_context.tacacs` -> `tacacs`); anything else is unchanged.
 */
export function toLocalConfigContextPath(pickedPath: string): string {
  for (const prefix of CONFIG_CONTEXT_ATTRIBUTE_PREFIXES) {
    if (pickedPath === prefix) return "";
    if (pickedPath.startsWith(`${prefix}.`)) return pickedPath.slice(prefix.length + 1);
  }
  return pickedPath;
}

const TRUTHY_STRINGS = new Set(["1", "true", "yes", "on"]);

/** Same truthiness the executor applies, so a hand-edited or imported "true" isn't saved back as false. */
function coerceBoolean(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  return typeof value === "string" && TRUTHY_STRINGS.has(value.trim().toLowerCase());
}

function coerceTemplateId(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function parseValueSource(raw: unknown): ValueSourceConfig {
  const source = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    type: source.type === "template" ? "template" : "attribute",
    attribute_path: typeof source.attribute_path === "string" ? source.attribute_path : "",
    template_id: coerceTemplateId(source.template_id),
  };
}

function parseUpdateEntry(raw: unknown): UpdateEntry {
  const entry = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    path: typeof entry.path === "string" ? entry.path : "",
    value_source: parseValueSource(entry.value_source),
  };
}

/** Always at least one row, so the update-mode form never renders empty. */
function parseUpdates(raw: unknown): UpdateEntry[] {
  if (!Array.isArray(raw) || raw.length === 0) return [emptyUpdateEntry()];
  return raw.map(parseUpdateEntry);
}

export function parseUpdateConfigContextConfig(
  config: Record<string, unknown>,
): UpdateConfigContextConfig {
  const rawMode = config.mode;
  const mode: UpdateConfigContextMode =
    rawMode === "update" || rawMode === "append" ? rawMode : "write";

  const rawIdentifier =
    config.device_identifier && typeof config.device_identifier === "object"
      ? (config.device_identifier as Record<string, unknown>)
      : {};

  return {
    mode,
    path: typeof config.path === "string" ? config.path : "",
    updates: parseUpdates(config.updates),
    create_local_if_missing: coerceBoolean(config.create_local_if_missing),
    value_source: parseValueSource(config.value_source),
    device_identifier: {
      mode: rawIdentifier.mode === "explicit" ? "explicit" : "from_context",
      id: typeof rawIdentifier.id === "string" ? rawIdentifier.id : "",
      name: typeof rawIdentifier.name === "string" ? rawIdentifier.name : "",
    },
  };
}

export function addUpdateEntry(updates: readonly UpdateEntry[]): UpdateEntry[] {
  return [...updates, emptyUpdateEntry()];
}

/** Removing the last remaining row leaves one empty row rather than none. */
export function removeUpdateEntry(updates: readonly UpdateEntry[], index: number): UpdateEntry[] {
  const remaining = updates.filter((_, position) => position !== index);
  return remaining.length > 0 ? remaining : [emptyUpdateEntry()];
}

export function patchUpdateEntry(
  updates: readonly UpdateEntry[],
  index: number,
  patch: Partial<UpdateEntry>,
): UpdateEntry[] {
  return updates.map((entry, position) => (position === index ? { ...entry, ...patch } : entry));
}

export function buildUpdateConfigContextConfig(
  config: Record<string, unknown>,
  patch: Partial<UpdateConfigContextConfig>,
): Record<string, unknown> {
  const current = parseUpdateConfigContextConfig(config);
  return {
    ...config,
    ...current,
    ...patch,
  };
}
