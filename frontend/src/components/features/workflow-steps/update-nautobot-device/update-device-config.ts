import type {
  NewInterfaceTypeConfig,
  CustomFieldRow,
  DeviceFieldKey,
  DeviceUpdateFieldsConfig,
  InterfacesSource,
  ParsedListConfig,
  ParsedListFieldKey,
  UpdateFieldSpec,
  UpdateNautobotDeviceConfig,
} from "./types";
import {
  NEW_INTERFACE_TYPE_MODES,
  DEFAULT_PARSED_LIST_CONFIG,
  DEVICE_FIELD_DEFINITIONS,
  PARSED_LIST_FIELD_DEFINITIONS,
} from "./types";

const EMPTY_FIELD_SPEC: UpdateFieldSpec = { enabled: false, value: "" };

function parseFieldSpec(raw: unknown): UpdateFieldSpec {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const record = raw as Record<string, unknown>;
    return {
      enabled: record.enabled === true,
      value: typeof record.value === "string" ? record.value : "",
    };
  }

  if (Array.isArray(raw)) {
    const cleaned = raw.map((item) => String(item).trim()).filter(Boolean);
    if (cleaned.length === 0) {
      return EMPTY_FIELD_SPEC;
    }
    return { enabled: true, value: cleaned.join(", ") };
  }

  if (typeof raw === "string") {
    const trimmed = raw.trim();
    if (!trimmed) {
      return EMPTY_FIELD_SPEC;
    }
    return { enabled: true, value: trimmed };
  }

  return EMPTY_FIELD_SPEC;
}

function parseCustomFields(raw: unknown): Record<string, UpdateFieldSpec> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }

  const result: Record<string, UpdateFieldSpec> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const name = key.trim();
    if (!name) continue;
    result[name] = parseFieldSpec(value);
  }
  return result;
}

export function parseUpdateFieldsConfig(raw: unknown): DeviceUpdateFieldsConfig {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }

  const record = raw as Record<string, unknown>;
  const parsed: DeviceUpdateFieldsConfig = {};

  for (const { key } of DEVICE_FIELD_DEFINITIONS) {
    if (key in record) {
      parsed[key] = parseFieldSpec(record[key]);
    }
  }

  if ("custom_fields" in record) {
    parsed.custom_fields = parseCustomFields(record.custom_fields);
  }

  return parsed;
}

export function countEnabledUpdateFields(config: Record<string, unknown>): number {
  const fields = parseUpdateFieldsConfig(config.update_fields);
  let count = 0;

  for (const { key } of DEVICE_FIELD_DEFINITIONS) {
    if (fields[key]?.enabled) {
      count += 1;
    }
  }

  const customFields = fields.custom_fields ?? {};
  count += Object.values(customFields).filter((item) => item.enabled).length;
  return count;
}

export function customFieldRowsFromConfig(
  fields: DeviceUpdateFieldsConfig | undefined,
): CustomFieldRow[] {
  const customFields = fields?.custom_fields ?? {};
  return Object.entries(customFields).map(([name, spec]) => ({
    id: crypto.randomUUID(),
    name,
    enabled: spec.enabled,
    value: spec.value,
  }));
}

export function customFieldsToConfig(rows: CustomFieldRow[]): Record<string, UpdateFieldSpec> {
  const result: Record<string, UpdateFieldSpec> = {};
  for (const row of rows) {
    const name = row.name.trim();
    if (!name) continue;
    result[name] = { enabled: row.enabled, value: row.value };
  }
  return result;
}

export function buildUpdateFieldsConfig(
  current: DeviceUpdateFieldsConfig | undefined,
  patch: Partial<DeviceUpdateFieldsConfig>,
): DeviceUpdateFieldsConfig {
  return {
    ...(current ?? {}),
    ...patch,
    custom_fields: patch.custom_fields ?? current?.custom_fields,
  };
}

export function patchDeviceFieldSpec(
  fields: DeviceUpdateFieldsConfig | undefined,
  key: DeviceFieldKey,
  patch: Partial<UpdateFieldSpec>,
): DeviceUpdateFieldsConfig {
  const current = fields?.[key] ?? EMPTY_FIELD_SPEC;
  return buildUpdateFieldsConfig(fields, {
    [key]: {
      enabled: patch.enabled ?? current.enabled,
      value: patch.value ?? current.value,
    },
  });
}

export function interfacesSourceFromConfig(config: Record<string, unknown>): InterfacesSource {
  if (config.interfaces_source === "nautobot_origin") return "nautobot_origin";
  if (config.interfaces_source === "parsed_list") return "parsed_list";
  return "manual";
}

function parseStringMap(raw: unknown): Partial<Record<ParsedListFieldKey, string>> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }
  const known = new Set<string>(PARSED_LIST_FIELD_DEFINITIONS.map((definition) => definition.key));
  const result: Partial<Record<ParsedListFieldKey, string>> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (known.has(key) && typeof value === "string") {
      result[key as ParsedListFieldKey] = value;
    }
  }
  return result;
}

function parseNewInterfaceType(raw: unknown): NewInterfaceTypeConfig {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { mode: "none", value: "" };
  }
  const record = raw as Record<string, unknown>;
  const mode = NEW_INTERFACE_TYPE_MODES.find((candidate) => candidate === record.mode) ?? "none";
  return { mode, value: typeof record.value === "string" ? record.value : "" };
}

/** Read the saved ``parsed_list`` setting; absent or malformed gives the defaults. */
export function parseParsedListConfig(raw: unknown): ParsedListConfig {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return DEFAULT_PARSED_LIST_CONFIG;
  }
  const record = raw as Record<string, unknown>;
  return {
    source_path: typeof record.source_path === "string" ? record.source_path : "",
    field_map: parseStringMap(record.field_map),
    fixed_values: parseStringMap(record.fixed_values),
    new_interface_type: parseNewInterfaceType(record.new_interface_type),
  };
}

/** Drop blank entries so the saved config only holds mappings that are really set. */
export function parsedListForSave(value: ParsedListConfig): ParsedListConfig {
  const clean = (map: Partial<Record<ParsedListFieldKey, string>>) => {
    const result: Partial<Record<ParsedListFieldKey, string>> = {};
    for (const [key, text] of Object.entries(map)) {
      const trimmed = (text ?? "").trim();
      if (trimmed) result[key as ParsedListFieldKey] = trimmed;
    }
    return result;
  };
  return {
    source_path: value.source_path.trim(),
    field_map: clean(value.field_map),
    fixed_values: clean(value.fixed_values),
    new_interface_type: {
      mode: value.new_interface_type.mode,
      value:
        value.new_interface_type.mode === "fixed" ? value.new_interface_type.value.trim() : "",
    },
  };
}

/** Interface sources that read the device's upstream data, so they need a workflow device. */
export const UPSTREAM_INTERFACE_SOURCES: ReadonlyArray<InterfacesSource> = [
  "nautobot_origin",
  "parsed_list",
];

/**
 * Why this source / device identifier / sync combination would fail at run time (null when it
 * is fine). Mirrors the checks in the step's ``_parse_config``.
 */
export function interfaceSourceProblem(
  source: InterfacesSource,
  identifierMode: string,
  options: { sync_interfaces?: boolean },
): string | null {
  if (UPSTREAM_INTERFACE_SOURCES.includes(source) && identifierMode === "explicit") {
    return (
      "This interface source reads data from the workflow's devices, so it cannot be used " +
      "with an explicit device identifier. Choose 'from context' or the manual source."
    );
  }
  if (source === "parsed_list" && options.sync_interfaces === true) {
    return (
      "sync_interfaces cannot be combined with a parsed list: an incomplete list would " +
      "delete the interfaces missing from it. Turn sync_interfaces off."
    );
  }
  return null;
}

/** Why the parsed-list setup cannot work yet (null when it is complete). */
export function parsedListProblem(value: ParsedListConfig): string | null {
  if (!value.source_path.trim()) return "Choose the list to read (source path).";
  if (!(value.field_map.name ?? "").trim()) return "Map the interface name to a column.";
  if (value.new_interface_type.mode === "fixed" && !value.new_interface_type.value.trim()) {
    return "Enter the type to create new interfaces with.";
  }
  return null;
}

export function parseUpdateNautobotDeviceConfig(
  config: Record<string, unknown>,
): UpdateNautobotDeviceConfig {
  return {
    ...(config as UpdateNautobotDeviceConfig),
    update_fields: parseUpdateFieldsConfig(config.update_fields),
  };
}
