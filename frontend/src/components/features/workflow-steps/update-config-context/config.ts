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
  value_source: ValueSourceConfig;
  device_identifier: DeviceIdentifierConfig;
}

export const DEFAULT_UPDATE_CONFIG_CONTEXT_CONFIG: UpdateConfigContextConfig = {
  mode: "write",
  path: "",
  value_source: { type: "attribute", attribute_path: "", template_id: null },
  device_identifier: { mode: "from_context", id: "", name: "" },
};

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
