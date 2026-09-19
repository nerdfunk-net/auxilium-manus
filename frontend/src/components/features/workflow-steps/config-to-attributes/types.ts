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
