export const IP_ID_KEY = "ip_id";
export const NAMESPACE_KEY = "namespace";
export const TYPE_KEY = "type";
export const ROLE_KEY = "role";
export const STATUS_KEY = "status";
export const DNS_NAME_KEY = "dns_name";
export const DESCRIPTION_KEY = "description";
export const IPS_FROM_INTERFACES_KEY = "ips_from_interfaces";
export const IP_VERSION_KEY = "ip_version";
export const DRY_RUN_KEY = "dry_run";

/** The fields the step can change; an empty one is left unchanged. */
export const UPDATE_FIELD_KEYS = [
  NAMESPACE_KEY,
  TYPE_KEY,
  ROLE_KEY,
  STATUS_KEY,
  DNS_NAME_KEY,
  DESCRIPTION_KEY,
] as const;

/** Address types Nautobot accepts for an IP address. */
export const IP_TYPE_OPTIONS = [
  { value: "host", label: "host" },
  { value: "dhcp", label: "dhcp" },
  { value: "slaac", label: "slaac" },
];

export const IP_VERSION_ANY = "any";

/** The IP versions the mode can be limited to (the select shows "any" for an empty value). */
export const IP_VERSION_OPTIONS = [
  { value: IP_VERSION_ANY, label: "IPv4 and IPv6" },
  { value: "4", label: "IPv4 only" },
  { value: "6", label: "IPv6 only" },
] as const;

/** The per-address tokens dns_name and description accept in the interfaces mode. */
export const ADDRESS_TOKENS = [
  "{ip.address}",
  "{ip.host}",
  "{interface.name}",
  "{interface.slug}",
] as const;

const NO_FIELD_PROBLEM = "configure at least one field to update";
export const INTERFACE_IP_ID_PROBLEM =
  "IP addresses from interfaces updates the addresses of the interfaces; clear ip_id";

/** True for a stored true / "true" (the step parses both). */
export function isFromInterfaces(config: Record<string, unknown>): boolean {
  const value = config[IPS_FROM_INTERFACES_KEY];
  return (
    value === true ||
    (typeof value === "string" && value.trim().toLowerCase() === "true")
  );
}

/** The config patch that switches the mode on: only ip_id is cleared, the values are kept. */
export function interfaceModeEnabledPatch(): Record<string, unknown> {
  return { [IPS_FROM_INTERFACES_KEY]: true, [IP_ID_KEY]: "" };
}

/** The version the select shows: "any" for an empty or unknown stored value. */
export function ipVersionFromConfig(config: Record<string, unknown>): string {
  const value = String(config[IP_VERSION_KEY] ?? "").trim();
  return value === "4" || value === "6" ? value : IP_VERSION_ANY;
}

/** The configuration problems the panel shows as warnings (empty = complete). */
export function configProblems(config: Record<string, unknown>): string[] {
  const text = (key: string) =>
    typeof config[key] === "string" ? (config[key] as string).trim() : "";
  const problems: string[] = [];
  if (isFromInterfaces(config)) {
    if (text(IP_ID_KEY)) problems.push(INTERFACE_IP_ID_PROBLEM);
  } else if (!text(IP_ID_KEY)) {
    problems.push("ip_id is not configured");
  }
  if (UPDATE_FIELD_KEYS.every((key) => !text(key)))
    problems.push(NO_FIELD_PROBLEM);
  return problems;
}

export { NO_FIELD_PROBLEM };
