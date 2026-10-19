/** Run-input text of a Get from User step: one ``name,ip_address,network_driver`` line per
 * device. The backend's ``workflow_steps.common.device_list.parse_device_list_text`` is the
 * authoritative parser; this only builds and reads the same shape for the Run Inputs widgets. */

/** Keep in sync with ``DEFAULT_NETWORK_DRIVER`` in backend/workflow_steps/common/device_list.py. */
export const DEFAULT_NETWORK_DRIVER = "cisco_ios";

/** Suggestions only — any Netmiko driver name (or alias) is accepted by the backend. */
export const NETWORK_DRIVER_SUGGESTIONS: readonly string[] = [
  "cisco_ios",
  "cisco_xe",
  "cisco_xr",
  "cisco_nxos",
  "cisco_asa",
  "juniper_junos",
  "arista_eos",
  "hp_comware",
];

export interface DeviceRow {
  name: string;
  ip: string;
  driver: string;
}

const IPV4_REGEX = /^(\d{1,3}\.){3}\d{1,3}(\/\d{1,2})?$/;
// Same patterns as validate_ip_address in backend/services/nautobot/common/validators.py.
const IPV6_REGEX = /^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(\/\d{1,3})?$/;

/** Lightweight heuristic: decides whether a bare token is typed into the IP or name slot. */
export function looksLikeIp(token: string): boolean {
  return IPV4_REGEX.test(token) || IPV6_REGEX.test(token);
}

/** Driver for a device picked from inventory search: its own when the inventory knows one,
 * else the step's default. */
export function driverForSuggestion(
  device: { network_driver?: string | null },
  defaultDriver: string,
): string {
  return device.network_driver?.trim() || defaultDriver;
}

/** Characters that would split a field or a line in the run-input text. */
const FIELD_BREAKERS = /[,\r\n]/g;

/** Strips what the line format cannot carry, so what a field shows is what is submitted. */
export function cleanDeviceField(value: string): string {
  return value.replace(FIELD_BREAKERS, "");
}

/** One line of run-input text, read the way the backend reads it; null when the backend would
 * reject the shape (more than ``name,ip,driver``). */
export function parseDeviceLine(
  line: string,
  defaultDriver: string = DEFAULT_NETWORK_DRIVER,
): DeviceRow | null {
  const trimmed = line.trim();
  if (!trimmed) {
    return null;
  }
  if (trimmed.includes(",")) {
    const parts = trimmed.split(",").map((part) => part.trim());
    if (parts.length > 3) {
      return null;
    }
    const [name = "", ip = "", driver = ""] = parts;
    return { name, ip, driver: driver || defaultDriver };
  }
  if (looksLikeIp(trimmed)) {
    return { name: "", ip: trimmed, driver: defaultDriver };
  }
  return { name: trimmed, ip: "", driver: defaultDriver };
}

export function parseDeviceListText(
  text: string,
  defaultDriver: string = DEFAULT_NETWORK_DRIVER,
): DeviceRow[] {
  return text
    .split("\n")
    .map((line) => parseDeviceLine(line, defaultDriver))
    .filter((row): row is DeviceRow => row !== null);
}

function rowToLine(row: DeviceRow): string {
  const name = cleanDeviceField(row.name).trim();
  const ip = cleanDeviceField(row.ip).trim();
  const driver = cleanDeviceField(row.driver).trim();
  if (!name && !ip) {
    return "";
  }
  if (driver) {
    return `${name},${ip},${driver}`;
  }
  return name && ip ? `${name},${ip}` : name || ip;
}

export function serializeDeviceRows(rows: readonly DeviceRow[]): string {
  return rows
    .map(rowToLine)
    .filter((line) => line.length > 0)
    .join("\n");
}
