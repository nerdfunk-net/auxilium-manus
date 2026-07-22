import type {
  CustomFieldRow,
  DeviceFieldKey,
  DeviceFieldsConfig,
  UpdateFieldSpec,
} from "./types";
import {
  OPTIONAL_DEVICE_FIELD_DEFINITIONS,
  RACK_FIELD_DEFINITIONS,
  REQUIRED_DEVICE_FIELD_DEFINITIONS,
} from "./types";

const EMPTY_FIELD_SPEC: UpdateFieldSpec = { enabled: false, value: "" };

const ALL_FIELD_KEYS: readonly DeviceFieldKey[] = [
  ...REQUIRED_DEVICE_FIELD_DEFINITIONS.map((def) => def.key),
  ...OPTIONAL_DEVICE_FIELD_DEFINITIONS.map((def) => def.key),
  ...RACK_FIELD_DEFINITIONS.map((def) => def.key),
];

function parseFieldSpec(raw: unknown): UpdateFieldSpec {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const record = raw as Record<string, unknown>;
    return {
      enabled: record.enabled === true,
      value: typeof record.value === "string" ? record.value : "",
    };
  }

  if (typeof raw === "string") {
    const trimmed = raw.trim();
    return trimmed ? { enabled: true, value: trimmed } : EMPTY_FIELD_SPEC;
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

export function parseDeviceFieldsConfig(raw: unknown): DeviceFieldsConfig {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }

  const record = raw as Record<string, unknown>;
  const parsed: DeviceFieldsConfig = {};

  for (const key of ALL_FIELD_KEYS) {
    if (key in record) {
      parsed[key] = parseFieldSpec(record[key]);
    }
  }

  if ("custom_fields" in record) {
    parsed.custom_fields = parseCustomFields(record.custom_fields);
  }

  return parsed;
}

export function requiredFieldSpec(
  fields: DeviceFieldsConfig | undefined,
  key: DeviceFieldKey,
): UpdateFieldSpec {
  const spec = fields?.[key] ?? EMPTY_FIELD_SPEC;
  // Required fields are always enabled regardless of stored value.
  return { enabled: true, value: spec.value };
}

export function countConfiguredRequiredFields(fields: DeviceFieldsConfig | undefined): number {
  return REQUIRED_DEVICE_FIELD_DEFINITIONS.filter(({ key }) => fields?.[key]?.value?.trim()).length;
}

export function countEnabledOptionalFields(fields: DeviceFieldsConfig | undefined): number {
  const optionalCount = OPTIONAL_DEVICE_FIELD_DEFINITIONS.filter(
    ({ key }) => fields?.[key]?.enabled,
  ).length;
  const customCount = Object.values(fields?.custom_fields ?? {}).filter(
    (item) => item.enabled,
  ).length;
  return optionalCount + customCount;
}

export function customFieldRowsFromConfig(fields: DeviceFieldsConfig | undefined): CustomFieldRow[] {
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

export function patchDeviceFieldSpec(
  fields: DeviceFieldsConfig | undefined,
  key: DeviceFieldKey,
  patch: Partial<UpdateFieldSpec>,
): DeviceFieldsConfig {
  const current = fields?.[key] ?? EMPTY_FIELD_SPEC;
  return {
    ...(fields ?? {}),
    [key]: {
      enabled: patch.enabled ?? current.enabled,
      value: patch.value ?? current.value,
    },
  };
}
