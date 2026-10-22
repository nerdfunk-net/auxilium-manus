export const IP_ID_KEY = "ip_id";
export const NAMESPACE_KEY = "namespace";
export const TYPE_KEY = "type";
export const ROLE_KEY = "role";
export const STATUS_KEY = "status";
export const DNS_NAME_KEY = "dns_name";
export const DESCRIPTION_KEY = "description";

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

const NO_FIELD_PROBLEM = "configure at least one field to update";

/** The configuration problems the panel shows as warnings (empty = complete). */
export function configProblems(config: Record<string, unknown>): string[] {
  const text = (key: string) =>
    typeof config[key] === "string" ? (config[key] as string).trim() : "";
  const problems: string[] = [];
  if (!text(IP_ID_KEY)) problems.push("ip_id is not configured");
  if (UPDATE_FIELD_KEYS.every((key) => !text(key))) problems.push(NO_FIELD_PROBLEM);
  return problems;
}

export { NO_FIELD_PROBLEM };
