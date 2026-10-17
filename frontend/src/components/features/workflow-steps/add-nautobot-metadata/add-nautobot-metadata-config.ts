import {
  fieldDefinitionsFor,
  type AddNautobotMetadataConfig,
  type DeviceTypeMetadata,
  type LocationMetadata,
  type MetadataType,
  type MetadataValues,
} from "./types";

// Mirrors backend/workflow_steps/add_nautobot_metadata/config.py::get_config() — the
// actual seed applied to a fresh node (the backend get-config endpoint does not seed nodes).
export const DEFAULT_LOCATION: LocationMetadata = {
  location_type: "",
  name: "",
  status: "Active",
  description: "",
  parent: "",
};

export const DEFAULT_DEVICE_TYPE: DeviceTypeMetadata = {
  manufacturer: "",
  role: "",
  model: "",
  height: "1",
  platform: "",
};

export const DEFAULT_METADATA_TYPE: MetadataType = "location";

export function metadataTypeFromConfig(config: AddNautobotMetadataConfig): MetadataType {
  return config.metadata_type === "device_type" ? "device_type" : DEFAULT_METADATA_TYPE;
}

function stringFields<T extends object>(defaults: T, raw: Partial<T> | undefined): T {
  const source: Record<string, unknown> = raw && typeof raw === "object" ? raw : {};
  const entries = Object.entries(defaults).map(([key, fallback]) => {
    const value = source[key];
    return [key, typeof value === "string" ? value : fallback];
  });
  return Object.fromEntries(entries) as T;
}

export function parseLocation(raw: Partial<LocationMetadata> | undefined): LocationMetadata {
  return stringFields(DEFAULT_LOCATION, raw);
}

export function parseDeviceType(raw: Partial<DeviceTypeMetadata> | undefined): DeviceTypeMetadata {
  return stringFields(DEFAULT_DEVICE_TYPE, raw);
}

export function valuesForType(
  config: AddNautobotMetadataConfig,
  metadataType: MetadataType,
): MetadataValues {
  return metadataType === "location"
    ? parseLocation(config.location)
    : parseDeviceType(config.device_type);
}

/** Required fields that have no value and no backend default (status/height default on the server). */
export function missingRequiredFields(
  metadataType: MetadataType,
  values: MetadataValues,
): string[] {
  const record = values as unknown as Record<string, string>;
  const defaulted = new Set(["status", "height"]);
  return fieldDefinitionsFor(metadataType)
    .filter(({ key, required }) => required && !defaulted.has(key) && !record[key]?.trim())
    .map(({ key }) => key);
}
