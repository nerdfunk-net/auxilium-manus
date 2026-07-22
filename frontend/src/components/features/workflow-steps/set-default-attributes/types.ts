export type ResourceType = "device" | "ip_address" | "ip_prefix";
export type DefaultsMode = "manual" | "git";

export interface AttributeFieldSpec {
  enabled: boolean;
  value: string;
}

export interface DeviceTypeDefaultSpec {
  enabled: boolean;
  model: string;
  manufacturer: string;
}

export interface InterfaceDefaultSpec {
  id: string;
  name: string;
  type: string;
  status: string;
  description: string;
  ip_addresses: string[];
}

export interface AttributesConfig {
  role: AttributeFieldSpec;
  status: AttributeFieldSpec;
  location: AttributeFieldSpec;
  platform: AttributeFieldSpec;
  software_version: AttributeFieldSpec;
  serial: AttributeFieldSpec;
  asset_tag: AttributeFieldSpec;
  tags: AttributeFieldSpec;
  device_type: DeviceTypeDefaultSpec;
  rack: AttributeFieldSpec;
  face: AttributeFieldSpec;
  position: AttributeFieldSpec;
  custom_fields: Record<string, AttributeFieldSpec>;
  interfaces: InterfaceDefaultSpec[];
}

export interface GitDefaultsConfig {
  git_source_id: string;
  filename_pattern: string;
}

export interface SetDefaultAttributesConfig {
  type?: ResourceType;
  mode?: DefaultsMode;
  overwrite?: boolean;
  attributes?: Partial<AttributesConfig>;
  git?: Partial<GitDefaultsConfig>;
}

export interface CustomFieldRow {
  id: string;
  name: string;
  enabled: boolean;
  value: string;
}

type ScalarAttributeKey =
  | "role"
  | "status"
  | "location"
  | "platform"
  | "software_version"
  | "serial"
  | "asset_tag"
  | "tags"
  | "rack"
  | "face"
  | "position";

interface FieldDefinition {
  key: ScalarAttributeKey;
  label: string;
  placeholder: string;
}

/** Every scalar field usable as a default value — none are required (they're defaults). */
export const OPTIONAL_ATTRIBUTE_FIELD_DEFINITIONS = [
  { key: "role", label: "Role", placeholder: "Network" },
  { key: "status", label: "Status", placeholder: "Active" },
  { key: "location", label: "Location", placeholder: "City A" },
  { key: "platform", label: "Platform", placeholder: "cisco_ios" },
  { key: "software_version", label: "Software version", placeholder: "17.9.1" },
  { key: "serial", label: "Serial number", placeholder: "" },
  { key: "asset_tag", label: "Asset tag", placeholder: "AST-0001" },
  { key: "tags", label: "Tags", placeholder: "production, lab" },
] as const satisfies ReadonlyArray<FieldDefinition>;

/** All-or-nothing rack placement group, same pattern as Add to Nautobot. */
export const RACK_FIELD_DEFINITIONS = [
  { key: "rack", label: "Rack", placeholder: "Rack-01" },
  { key: "face", label: "Face", placeholder: "front or rear" },
  { key: "position", label: "Position", placeholder: "12" },
] as const satisfies ReadonlyArray<FieldDefinition>;

export const RESOURCE_TYPE_OPTIONS: ReadonlyArray<{
  value: ResourceType;
  label: string;
  enabled: boolean;
}> = [
  { value: "device", label: "Device", enabled: true },
  { value: "ip_address", label: "IP Address (coming soon)", enabled: false },
  { value: "ip_prefix", label: "IP Prefix (coming soon)", enabled: false },
];
