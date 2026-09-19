export const ATTRIBUTE_GROUPS = [
  { key: "interfaces", label: "Add Interfaces" },
] as const;

export type AttributeGroupKey = (typeof ATTRIBUTE_GROUPS)[number]["key"];

export const SOURCE_FORMAT_OPTIONS = [
  { value: "cisco_config_parser", label: "Cisco Config Parser (Parse Cisco Config)" },
  { value: "genie", label: "Genie (pyATS Get & Parse Config)" },
  { value: "batfish", label: "Batfish (Extract Facts)" },
] as const;

export type SourceFormat = (typeof SOURCE_FORMAT_OPTIONS)[number]["value"];

export const PRIMARY_IPV4_STRATEGIES = [
  {
    key: "management_interface",
    label: "Use Management Interface",
    description: "First interface whose name starts with \"Management\" or \"Mgmt\" (case-insensitive).",
  },
  {
    key: "loopback_highest",
    label: "Use Loopback Interface (highest Loopback first)",
    description: "Loopback interface with the highest numeric suffix, e.g. Loopback100 over Loopback0.",
  },
  {
    key: "loopback_lowest",
    label: "Use Loopback Interface (lowest Loopback first)",
    description: "Loopback interface with the lowest numeric suffix, e.g. Loopback0 over Loopback100.",
  },
  {
    key: "custom_interface",
    label: "Custom Interface Name / Regex",
    description: "First interface whose name matches the regex entered below.",
  },
] as const;

export type PrimaryIpv4Strategy = (typeof PRIMARY_IPV4_STRATEGIES)[number]["key"];

export const DEFAULT_PRIMARY_IPV4_PRIORITY: PrimaryIpv4Strategy[] = PRIMARY_IPV4_STRATEGIES.map(
  (strategy) => strategy.key,
);
