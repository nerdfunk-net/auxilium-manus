/**
 * Selectable Nautobot attributes for the device mapping.
 *
 * Keep in sync with `NAUTOBOT_TARGETS` / `CORE_TARGETS` in
 * `backend/services/git/device_mapping.py` (internal UUIDs are intentionally absent).
 */
export interface NautobotTarget {
  value: string;
  label: string;
  group: string;
  /** Also populates a core workflow device field (name, IP, platform, driver). */
  core: boolean;
}

export const NAME_TARGET = "name";

/** Pseudo target: skip this column/key. Mirrors `IGNORE_TARGET` in the backend. */
export const IGNORE_TARGET = "_ignore";

/**
 * Pseudo target: a true/false column flagging the interface whose IP becomes the device's
 * primary IPv4 address. Feeds no Nautobot field. Mirrors `PRIMARY_FLAG_TARGET` in the backend.
 */
export const PRIMARY_FLAG_TARGET = "_is_primary";

export const NAUTOBOT_TARGETS: readonly NautobotTarget[] = [
  { value: "name", label: "Device name", group: "Device", core: true },
  { value: "hostname", label: "Hostname", group: "Device", core: false },
  { value: "serial", label: "Serial", group: "Device", core: false },
  { value: "asset_tag", label: "Asset tag", group: "Device", core: false },
  { value: "position", label: "Position", group: "Device", core: false },
  { value: "face", label: "Face", group: "Device", core: false },
  { value: "primary_ip4.address", label: "Primary IPv4 address", group: "Network", core: true },
  { value: "primary_ip4.description", label: "Primary IPv4 description", group: "Network", core: false },
  { value: "primary_ip4.dns_name", label: "Primary IPv4 DNS name", group: "Network", core: false },
  { value: "primary_ip4.status.name", label: "Primary IPv4 status", group: "Network", core: false },
  {
    value: "primary_ip4.parent.namespace.name",
    label: "Primary IPv4 namespace",
    group: "Network",
    core: false,
  },
  { value: "role.name", label: "Role", group: "Role", core: false },
  { value: "device_type.model", label: "Device type model", group: "Device type", core: false },
  { value: "device_type.manufacturer.name", label: "Manufacturer", group: "Device type", core: false },
  { value: "platform.name", label: "Platform", group: "Platform", core: true },
  { value: "platform.network_driver", label: "Network driver", group: "Platform", core: true },
  { value: "location.name", label: "Location", group: "Location", core: false },
  { value: "location.description", label: "Location description", group: "Location", core: false },
  { value: "location.parent.name", label: "Parent location", group: "Location", core: false },
  { value: "status.name", label: "Status", group: "Status", core: false },
  { value: "interfaces.name", label: "Interface name", group: "Interface", core: false },
  { value: "interfaces.description", label: "Interface description", group: "Interface", core: false },
  { value: "interfaces.type", label: "Interface type", group: "Interface", core: false },
  { value: "interfaces.mac_address", label: "Interface MAC address", group: "Interface", core: false },
  { value: "interfaces.mtu", label: "Interface MTU", group: "Interface", core: false },
  { value: "interfaces.status.name", label: "Interface status", group: "Interface", core: false },
  {
    value: "interfaces.ip_addresses.address",
    label: "Interface IP address",
    group: "Interface",
    core: false,
  },
  {
    value: "interfaces.ip_addresses.parent.namespace.name",
    label: "Interface IP namespace",
    group: "Interface",
    core: false,
  },
] as const;

export const INTERFACE_PREFIX = "interfaces.";
export const INTERFACE_NAME_TARGET = "interfaces.name";
export const PRIMARY_IP_PREFIX = "primary_ip4.";
export const PRIMARY_IP_TARGET = "primary_ip4.address";
export const PRIMARY_IP_NAMESPACE_TARGET = "primary_ip4.parent.namespace.name";
export const INTERFACE_IP_TARGET = "interfaces.ip_addresses.address";
export const INTERFACE_IP_NAMESPACE_TARGET = "interfaces.ip_addresses.parent.namespace.name";

/**
 * Custom values are not Nautobot data: `custom.<name>` for any simple name. They end up in the
 * `custom` attribute bag of the device. Mirrors `CUSTOM_PREFIX` in the backend.
 */
export const CUSTOM_PREFIX = "custom.";
/** Combobox option value that stands for "a custom value of your choice". */
export const CUSTOM_OPTION = CUSTOM_PREFIX;

export function isCustomTarget(value: string): boolean {
  return value.startsWith(CUSTOM_PREFIX);
}

export function customName(value: string): string {
  return isCustomTarget(value) ? value.slice(CUSTOM_PREFIX.length) : "";
}

export function isValidCustomTarget(value: string): boolean {
  return isCustomTarget(value) && CUSTOM_FIELD_NAME.test(customName(value));
}

/** Custom fields are open-ended: `custom_fields.<name>` for any simple name. */
export const CUSTOM_FIELD_PREFIX = "custom_fields.";
/** Combobox option value that stands for "a custom field of your choice". */
export const CUSTOM_FIELD_OPTION = CUSTOM_FIELD_PREFIX;
const CUSTOM_FIELD_NAME = /^[A-Za-z0-9_]+$/;

export function isCustomFieldTarget(value: string): boolean {
  return value.startsWith(CUSTOM_FIELD_PREFIX);
}

export function customFieldName(value: string): string {
  return isCustomFieldTarget(value) ? value.slice(CUSTOM_FIELD_PREFIX.length) : "";
}

export function isValidCustomFieldTarget(value: string): boolean {
  return isCustomFieldTarget(value) && CUSTOM_FIELD_NAME.test(customFieldName(value));
}

const TARGETS_BY_VALUE: ReadonlyMap<string, NautobotTarget> = new Map(
  NAUTOBOT_TARGETS.map((target) => [target.value, target]),
);

export function targetLabel(value: string): string {
  if (value === IGNORE_TARGET) {
    return "Ignore this column";
  }
  if (value === PRIMARY_FLAG_TARGET) {
    return "Primary interface flag (true/false)";
  }
  if (isCustomTarget(value)) {
    return `Custom value · ${customName(value) || "…"}`;
  }
  if (isCustomFieldTarget(value)) {
    return `Custom field · ${customFieldName(value) || "…"}`;
  }
  const target = TARGETS_BY_VALUE.get(value);
  return target ? `${target.group} · ${target.label}` : value;
}

export function isKnownTarget(value: string): boolean {
  return (
    value === IGNORE_TARGET ||
    value === PRIMARY_FLAG_TARGET ||
    TARGETS_BY_VALUE.has(value) ||
    isValidCustomFieldTarget(value) ||
    isValidCustomTarget(value)
  );
}
