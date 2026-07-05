import type {
  CustomFieldRow,
  DeviceFieldKey,
  DeviceUpdateFieldsConfig,
  UpdateFieldSpec,
  UpdateNautobotDeviceConfig,
} from "./types";
import { DEVICE_FIELD_DEFINITIONS } from "./types";

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

export function parseUpdateNautobotDeviceConfig(
  config: Record<string, unknown>,
): UpdateNautobotDeviceConfig {
  return {
    ...(config as UpdateNautobotDeviceConfig),
    update_fields: parseUpdateFieldsConfig(config.update_fields),
  };
}
