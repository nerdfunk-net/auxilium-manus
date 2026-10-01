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

export interface UpdateConfigContextConfig {
  mode: UpdateConfigContextMode;
  path: string;
  /** update/append with a path: copy the path's top-level key from the global config context when the device has no local copy. */
  create_local_if_missing: boolean;
  value_source: ValueSourceConfig;
  device_identifier: DeviceIdentifierConfig;
}

export const DEFAULT_UPDATE_CONFIG_CONTEXT_CONFIG: UpdateConfigContextConfig = {
  mode: "write",
  path: "",
  create_local_if_missing: false,
  value_source: { type: "attribute", attribute_path: "", template_id: null },
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

export function parseUpdateConfigContextConfig(
  config: Record<string, unknown>,
): UpdateConfigContextConfig {
  const rawMode = config.mode;
  const mode: UpdateConfigContextMode =
    rawMode === "update" || rawMode === "append" ? rawMode : "write";

  const rawValueSource =
    config.value_source && typeof config.value_source === "object"
      ? (config.value_source as Record<string, unknown>)
      : {};
  const valueSourceType: ValueSourceType =
    rawValueSource.type === "template" ? "template" : "attribute";

  const rawIdentifier =
    config.device_identifier && typeof config.device_identifier === "object"
      ? (config.device_identifier as Record<string, unknown>)
      : {};

  return {
    mode,
    path: typeof config.path === "string" ? config.path : "",
    create_local_if_missing: coerceBoolean(config.create_local_if_missing),
    value_source: {
      type: valueSourceType,
      attribute_path:
        typeof rawValueSource.attribute_path === "string" ? rawValueSource.attribute_path : "",
      template_id: coerceTemplateId(rawValueSource.template_id),
    },
    device_identifier: {
      mode: rawIdentifier.mode === "explicit" ? "explicit" : "from_context",
      id: typeof rawIdentifier.id === "string" ? rawIdentifier.id : "",
      name: typeof rawIdentifier.name === "string" ? rawIdentifier.name : "",
    },
  };
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
