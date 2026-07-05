export type DeviceIdentifierMode = "from_context" | "explicit";

export interface DeviceIdentifierConfig {
  mode: DeviceIdentifierMode;
  id?: string;
  name?: string;
}

export interface UpdateFieldSpec {
  enabled: boolean;
  value: string;
}

export type DeviceFieldKey =
  | "name"
  | "location"
  | "serial"
  | "role"
  | "status"
  | "device_type"
  | "platform"
  | "software_version"
  | "tags";

export interface CustomFieldRow {
  id: string;
  name: string;
  enabled: boolean;
  value: string;
}

export interface DeviceUpdateFieldsConfig {
  name?: UpdateFieldSpec;
  location?: UpdateFieldSpec;
  serial?: UpdateFieldSpec;
  role?: UpdateFieldSpec;
  status?: UpdateFieldSpec;
  device_type?: UpdateFieldSpec;
  platform?: UpdateFieldSpec;
  software_version?: UpdateFieldSpec;
  tags?: UpdateFieldSpec;
  custom_fields?: Record<string, UpdateFieldSpec>;
}

export interface InterfaceUpdateConfig {
  id?: string;
  name: string;
  type?: string;
  status?: string;
  ip_address?: string;
  namespace?: string;
  description?: string;
  is_primary_ipv4?: boolean;
}

export interface UpdateNautobotDeviceConfig {
  nautobot_source_id?: string;
  device_identifier?: DeviceIdentifierConfig;
  update_fields?: DeviceUpdateFieldsConfig;
  interfaces?: InterfaceUpdateConfig[];
  add_prefix?: boolean;
  default_prefix_length?: string;
  sync_interfaces?: boolean;
}

export const DEVICE_FIELD_DEFINITIONS = [
  { key: "name", label: "Device name", placeholder: "cityA or {custom.name}" },
  { key: "location", label: "Location", placeholder: "{nautobot.origin}" },
  { key: "serial", label: "Serial number", placeholder: "{custom.serial | default('N/A')}" },
  { key: "role", label: "Device role", placeholder: "access-switch" },
  { key: "status", label: "Device status", placeholder: "active" },
  { key: "device_type", label: "Device type", placeholder: "C9300-24T" },
  { key: "platform", label: "Platform", placeholder: "{nautobot.origin}" },
  { key: "software_version", label: "Software version", placeholder: "17.9.1" },
  { key: "tags", label: "Tags", placeholder: "lab, prod or {custom.tags}" },
] as const satisfies ReadonlyArray<{
  key: DeviceFieldKey;
  label: string;
  placeholder: string;
}>;

export const UPDATE_FIELD_VALUE_HELP =
  "Fixed value (cityA), {nautobot.origin}, {custom.my_field}, or {custom.my_field | default('fallback')}";
