export type DeviceFieldKey =
  | "name"
  | "role"
  | "status"
  | "location"
  | "device_type"
  | "platform"
  | "software_version"
  | "serial"
  | "asset_tag"
  | "tags"
  | "rack"
  | "face"
  | "position";

export interface UpdateFieldSpec {
  enabled: boolean;
  value: string;
}

export interface CustomFieldRow {
  id: string;
  name: string;
  enabled: boolean;
  value: string;
}

export type DeviceFieldsConfig = Partial<Record<DeviceFieldKey, UpdateFieldSpec>> & {
  custom_fields?: Record<string, UpdateFieldSpec>;
};

export interface InterfaceCreateConfig {
  id?: string;
  name: string;
  type?: string;
  status?: string;
  ip_address?: string;
  namespace?: string;
  description?: string;
  is_primary_ipv4?: boolean;
}

export type VirtualChassisMode = "none" | "join" | "create";

export interface VirtualChassisConfig {
  mode: VirtualChassisMode;
  id?: string;
  name?: string;
}

export interface AddToNautobotConfig {
  nautobot_source_id?: string;
  device_fields?: DeviceFieldsConfig;
  interfaces?: InterfaceCreateConfig[];
  add_prefix?: boolean;
  default_prefix_length?: string;
  virtual_chassis?: VirtualChassisConfig;
  dry_run?: boolean;
}

interface FieldDefinition {
  key: DeviceFieldKey;
  label: string;
  placeholder: string;
}

/** Required to create a device — always enabled, no checkbox. */
export const REQUIRED_DEVICE_FIELD_DEFINITIONS = [
  { key: "name", label: "Device name", placeholder: "{parsed.cisco_config.hostname}" },
  { key: "role", label: "Role", placeholder: "{nautobot.origin}" },
  { key: "status", label: "Status", placeholder: "{nautobot.origin | default('Active')}" },
  { key: "location", label: "Location", placeholder: "{nautobot.origin}" },
  { key: "device_type", label: "Device type", placeholder: "{nautobot.origin}" },
] as const satisfies ReadonlyArray<FieldDefinition>;

/** Optional device attributes — checkbox + value, same pattern as Update Device. */
export const OPTIONAL_DEVICE_FIELD_DEFINITIONS = [
  { key: "platform", label: "Platform", placeholder: "{nautobot.origin}" },
  { key: "software_version", label: "Software version", placeholder: "17.9.1" },
  { key: "serial", label: "Serial number", placeholder: "{custom.serial | default('N/A')}" },
  { key: "asset_tag", label: "Asset tag", placeholder: "AST-0001" },
  { key: "tags", label: "Tags", placeholder: "lab, prod or {custom.tags}" },
] as const satisfies ReadonlyArray<FieldDefinition>;

/** Optional rack placement — all-or-nothing group, omit rack to skip entirely. */
export const RACK_FIELD_DEFINITIONS = [
  { key: "rack", label: "Rack", placeholder: "Rack-01" },
  { key: "face", label: "Face", placeholder: "front or rear" },
  { key: "position", label: "Position", placeholder: "12" },
] as const satisfies ReadonlyArray<FieldDefinition>;

export const DEVICE_FIELD_VALUE_HELP =
  "Fixed value (active), {path.to.value}, {nautobot.origin}, or {path | default('fallback')}";
