export const ATTRIBUTE_GROUPS = [
  { key: "interfaces", label: "Poll all Interfaces" },
  { key: "custom_fields", label: "Poll Custom Fields" },
  { key: "tags", label: "Poll Tags" },
  { key: "config_context", label: "Poll Config Context" },
  { key: "secret_groups", label: "Poll Secret Groups" },
  { key: "console_ports", label: "Poll Console Ports and Console Server Ports" },
  { key: "power_ports", label: "Poll Power Ports and Power Outlets" },
] as const;

export type AttributeGroupKey = (typeof ATTRIBUTE_GROUPS)[number]["key"];
