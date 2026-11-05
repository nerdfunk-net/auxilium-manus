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
  mac_address?: string;
  port_type?: string;
  mode?: string;
  /** Kbps (Nautobot's unit); a text such as "1 Gbit" is converted by the backend. */
  speed?: string;
  duplex?: string;
  mtu?: string;
  vrf?: string;
}

export type InterfacesSource = "manual" | "nautobot_origin" | "parsed_list";

/** Interface fields a parsed-list column can be mapped to (``name`` is required). */
export type ParsedListFieldKey =
  | "name"
  | "mac_address"
  | "type"
  | "port_type"
  | "mode"
  | "speed"
  | "duplex"
  | "mtu"
  | "vrf"
  | "description";

/** How to pick the type of a Nautobot interface that has to be created (never changes an existing one). */
export type NewInterfaceTypeMode = "none" | "infer" | "fixed";

export interface NewInterfaceTypeConfig {
  mode: NewInterfaceTypeMode;
  /** Nautobot interface type slug; only used when ``mode`` is "fixed". */
  value: string;
}

export interface ParsedListConfig {
  /** Attribute path of a list of objects, e.g. parsed.<step>.<command>.parsed */
  source_path: string;
  /** Interface field -> column name in the list. */
  field_map: Partial<Record<ParsedListFieldKey, string>>;
  /** Interface field -> one value used for every row (patches existing interfaces too). */
  fixed_values: Partial<Record<ParsedListFieldKey, string>>;
  /** Type used only for interfaces that do not exist in Nautobot yet. */
  new_interface_type: NewInterfaceTypeConfig;
}

export interface UpdateNautobotDeviceConfig {
  nautobot_source_id?: string;
  device_identifier?: DeviceIdentifierConfig;
  update_fields?: DeviceUpdateFieldsConfig;
  interfaces_source?: InterfacesSource;
  interfaces?: InterfaceUpdateConfig[];
  parsed_list?: ParsedListConfig;
  add_prefix?: boolean;
  default_prefix_length?: string;
  sync_interfaces?: boolean;
  dry_run?: boolean;
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

export const PARSED_LIST_FIELD_DEFINITIONS = [
  { key: "name", label: "Interface name", placeholder: "interface", required: true },
  { key: "mac_address", label: "MAC address", placeholder: "mac_address" },
  { key: "mtu", label: "MTU", placeholder: "mtu" },
  { key: "speed", label: "Speed", placeholder: "bandwidth" },
  { key: "duplex", label: "Duplex", placeholder: "duplex" },
  { key: "description", label: "Description", placeholder: "description" },
  { key: "type", label: "Type (changes existing interfaces)", placeholder: "(leave empty)" },
  { key: "port_type", label: "Port type", placeholder: "(column)" },
  { key: "mode", label: "802.1Q mode", placeholder: "(column)" },
  { key: "vrf", label: "VRF", placeholder: "(column)" },
] as const satisfies ReadonlyArray<{
  key: ParsedListFieldKey;
  label: string;
  placeholder: string;
  required?: boolean;
}>;

/** Fields that make sense as one fixed value for every row. */
export const PARSED_LIST_FIXED_FIELDS: ReadonlyArray<ParsedListFieldKey> = [
  "port_type",
  "mode",
  "duplex",
  "vrf",
];

export const INTERFACE_DUPLEX_OPTIONS = ["auto", "full", "half"] as const;
export const INTERFACE_MODE_OPTIONS = ["access", "tagged", "tagged-all"] as const;

export const DEFAULT_PARSED_LIST_CONFIG: ParsedListConfig = {
  source_path: "",
  field_map: { name: "interface", mac_address: "mac_address" },
  fixed_values: {},
  new_interface_type: { mode: "none", value: "" },
};

export const NEW_INTERFACE_TYPE_MODES: ReadonlyArray<NewInterfaceTypeMode> = [
  "none",
  "infer",
  "fixed",
];
