/** Names of the opt-in data classes the server reports as withheld, as the settings page shows them. */
export const DATA_CLASS_LABELS: Record<string, string> = {
  inventory_data: "Inventory and device attributes",
  device_addresses: "Addresses and serial numbers",
  custom_fields: "Custom fields",
  config_context: "Config context",
  content_data: "Run and device content",
};

export function dataClassLabel(dataClass: string): string {
  return DATA_CLASS_LABELS[dataClass] ?? dataClass;
}
