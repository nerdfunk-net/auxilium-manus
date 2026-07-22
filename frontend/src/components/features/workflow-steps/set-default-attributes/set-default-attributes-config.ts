import type {
  AttributeFieldSpec,
  AttributesConfig,
  CustomFieldRow,
  DefaultsMode,
  DeviceTypeDefaultSpec,
  GitDefaultsConfig,
  InterfaceDefaultSpec,
  ResourceType,
} from "./types";

const EMPTY_FIELD_SPEC: AttributeFieldSpec = { enabled: false, value: "" };
const EMPTY_DEVICE_TYPE_SPEC: DeviceTypeDefaultSpec = {
  enabled: false,
  model: "",
  manufacturer: "",
};

export function resourceTypeFromConfig(config: Record<string, unknown>): ResourceType {
  const raw = config.type;
  return raw === "ip_address" || raw === "ip_prefix" ? raw : "device";
}

export function modeFromConfig(config: Record<string, unknown>): DefaultsMode {
  return config.mode === "git" ? "git" : "manual";
}

export function overwriteFromConfig(config: Record<string, unknown>): boolean {
  return config.overwrite === true;
}

function parseFieldSpec(raw: unknown): AttributeFieldSpec {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const record = raw as Record<string, unknown>;
    return {
      enabled: record.enabled === true,
      value: typeof record.value === "string" ? record.value : "",
    };
  }
  return EMPTY_FIELD_SPEC;
}

function parseDeviceTypeSpec(raw: unknown): DeviceTypeDefaultSpec {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const record = raw as Record<string, unknown>;
    return {
      enabled: record.enabled === true,
      model: typeof record.model === "string" ? record.model : "",
      manufacturer: typeof record.manufacturer === "string" ? record.manufacturer : "",
    };
  }
  return EMPTY_DEVICE_TYPE_SPEC;
}

function parseCustomFields(raw: unknown): Record<string, AttributeFieldSpec> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }
  const result: Record<string, AttributeFieldSpec> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const name = key.trim();
    if (!name) continue;
    result[name] = parseFieldSpec(value);
  }
  return result;
}

function parseInterfaces(raw: unknown): InterfaceDefaultSpec[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map((item) => {
    const record = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
    const ipAddresses = Array.isArray(record.ip_addresses)
      ? record.ip_addresses.filter((ip): ip is string => typeof ip === "string")
      : [];
    return {
      id: typeof record.id === "string" && record.id ? record.id : crypto.randomUUID(),
      name: typeof record.name === "string" ? record.name : "",
      type: typeof record.type === "string" ? record.type : "",
      status: typeof record.status === "string" ? record.status : "",
      description: typeof record.description === "string" ? record.description : "",
      ip_addresses: ipAddresses,
    };
  });
}

export function parseAttributesConfig(config: Record<string, unknown>): AttributesConfig {
  const raw = config.attributes;
  const record =
    raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  return {
    role: parseFieldSpec(record.role),
    status: parseFieldSpec(record.status),
    location: parseFieldSpec(record.location),
    platform: parseFieldSpec(record.platform),
    software_version: parseFieldSpec(record.software_version),
    serial: parseFieldSpec(record.serial),
    asset_tag: parseFieldSpec(record.asset_tag),
    tags: parseFieldSpec(record.tags),
    device_type: parseDeviceTypeSpec(record.device_type),
    rack: parseFieldSpec(record.rack),
    face: parseFieldSpec(record.face),
    position: parseFieldSpec(record.position),
    custom_fields: parseCustomFields(record.custom_fields),
    interfaces: parseInterfaces(record.interfaces),
  };
}

export function parseGitConfig(config: Record<string, unknown>): GitDefaultsConfig {
  const raw = config.git;
  const record =
    raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  return {
    git_source_id: typeof record.git_source_id === "string" ? record.git_source_id : "",
    filename_pattern:
      typeof record.filename_pattern === "string" && record.filename_pattern
        ? record.filename_pattern
        : "*.yaml",
  };
}

const SCALAR_KEYS: Array<keyof AttributesConfig> = [
  "role",
  "status",
  "location",
  "platform",
  "software_version",
  "serial",
  "asset_tag",
  "tags",
  "rack",
  "face",
  "position",
];

export function countConfiguredFields(attributes: AttributesConfig): number {
  let count = 0;
  for (const key of SCALAR_KEYS) {
    const spec = attributes[key] as AttributeFieldSpec;
    if (spec.enabled && spec.value.trim()) {
      count += 1;
    }
  }
  if (
    attributes.device_type.enabled &&
    (attributes.device_type.model.trim() || attributes.device_type.manufacturer.trim())
  ) {
    count += 1;
  }
  count += Object.values(attributes.custom_fields).filter(
    (spec) => spec.enabled && spec.value.trim(),
  ).length;
  count += attributes.interfaces.filter((iface) => iface.name.trim()).length;
  return count;
}

export function patchFieldSpec(
  attributes: AttributesConfig,
  key: keyof AttributesConfig,
  patch: Partial<AttributeFieldSpec>,
): AttributesConfig {
  const current = attributes[key] as AttributeFieldSpec;
  return { ...attributes, [key]: { ...current, ...patch } };
}

export function customFieldRowsFromConfig(attributes: AttributesConfig): CustomFieldRow[] {
  return Object.entries(attributes.custom_fields).map(([name, spec]) => ({
    id: crypto.randomUUID(),
    name,
    enabled: spec.enabled,
    value: spec.value,
  }));
}

export function customFieldsToConfig(rows: CustomFieldRow[]): Record<string, AttributeFieldSpec> {
  const result: Record<string, AttributeFieldSpec> = {};
  for (const row of rows) {
    const name = row.name.trim();
    if (!name) continue;
    result[name] = { enabled: row.enabled, value: row.value };
  }
  return result;
}

export function newInterfaceRow(): InterfaceDefaultSpec {
  return {
    id: crypto.randomUUID(),
    name: "",
    type: "",
    status: "",
    description: "",
    ip_addresses: [],
  };
}
