export type DeviceIdentifierMode = "from_context" | "explicit";

export interface DeviceIdentifierConfig {
  mode: DeviceIdentifierMode;
  id?: string;
  name?: string;
}

export interface DeviceUpdateFields {
  name?: string;
  location?: string;
  serial?: string;
  role?: string;
  status?: string;
  device_type?: string;
  platform?: string;
  software_version?: string;
  tags?: string[];
  custom_fields?: Record<string, string>;
}

export interface InterfaceUpdateConfig {
  id: string;
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
  update_fields?: DeviceUpdateFields;
  interfaces?: InterfaceUpdateConfig[];
  add_prefix?: boolean;
  default_prefix_length?: string;
  sync_interfaces?: boolean;
}

export const DEVICE_FIELD_DEFINITIONS = [
  { key: "name", label: "Device name" },
  { key: "location", label: "Location" },
  { key: "serial", label: "Serial number" },
  { key: "role", label: "Device role" },
  { key: "status", label: "Device status" },
  { key: "device_type", label: "Device type" },
  { key: "platform", label: "Platform" },
  { key: "software_version", label: "Software version" },
] as const;
