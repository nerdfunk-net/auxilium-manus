export const ATTRIBUTE_GROUPS = [
  { key: "layer3_interfaces", label: "Layer3 Interfaces" },
] as const;

export type AttributeGroupKey = (typeof ATTRIBUTE_GROUPS)[number]["key"];
