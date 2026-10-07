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
  { value: "role.name", label: "Role", group: "Role", core: false },
  { value: "device_type.model", label: "Device type model", group: "Device type", core: false },
  { value: "device_type.manufacturer.name", label: "Manufacturer", group: "Device type", core: false },
  { value: "platform.name", label: "Platform", group: "Platform", core: true },
  { value: "platform.network_driver", label: "Network driver", group: "Platform", core: true },
  { value: "location.name", label: "Location", group: "Location", core: false },
  { value: "location.description", label: "Location description", group: "Location", core: false },
  { value: "location.parent.name", label: "Parent location", group: "Location", core: false },
  { value: "status.name", label: "Status", group: "Status", core: false },
] as const;

const TARGETS_BY_VALUE: ReadonlyMap<string, NautobotTarget> = new Map(
  NAUTOBOT_TARGETS.map((target) => [target.value, target]),
);

export function targetLabel(value: string): string {
  const target = TARGETS_BY_VALUE.get(value);
  return target ? `${target.group} · ${target.label}` : value;
}

export function isKnownTarget(value: string): boolean {
  return TARGETS_BY_VALUE.has(value);
}
