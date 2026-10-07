/** Config shape for the add-nautobot-metadata step (mirrors backend/workflow_steps/add_nautobot_metadata/config.py). */

export type MetadataType = "location" | "device_type";

export const METADATA_TYPE_OPTIONS: ReadonlyArray<{ value: MetadataType; label: string }> = [
  { value: "location", label: "Location" },
  { value: "device_type", label: "Device Type" },
];

export interface LocationMetadata {
  location_type: string;
  name: string;
  status: string;
  description: string;
  parent: string;
}

export interface DeviceTypeMetadata {
  manufacturer: string;
  role: string;
  model: string;
  height: string;
  platform: string;
}

export interface AddNautobotMetadataConfig {
  nautobot_source_id?: string;
  metadata_type?: MetadataType;
  location?: Partial<LocationMetadata>;
  device_type?: Partial<DeviceTypeMetadata>;
}

export type MetadataValues = LocationMetadata | DeviceTypeMetadata;

export interface MetadataFieldDefinition {
  key: string;
  label: string;
  placeholder: string;
  required: boolean;
  /** Field name understood by GET sources/nautobot/field-values/{field}; omitted = free text only. */
  optionsField?: string;
  hint?: string;
}

export const LOCATION_FIELD_DEFINITIONS: ReadonlyArray<MetadataFieldDefinition> = [
  {
    key: "location_type",
    label: "Location type",
    placeholder: "Site  or  {custom.location_type}",
    required: true,
    optionsField: "location_type",
  },
  {
    key: "name",
    label: "Name",
    placeholder: "Berlin  or  {custom.location_name}",
    required: true,
  },
  {
    key: "status",
    label: "Status",
    placeholder: "Active  or  {nautobot.status}",
    required: true,
    optionsField: "location_status",
    hint: "Defaults to Active when left empty.",
  },
  {
    key: "description",
    label: "Description",
    placeholder: "Optional  or  {custom.description}",
    required: false,
    hint: "May be empty. A {path} that is missing on a device is treated as empty.",
  },
  {
    key: "parent",
    label: "Parent location",
    placeholder: "Optional  or  {custom.parent}",
    required: false,
    optionsField: "location",
    hint: "Needed when the location type is nested under another type.",
  },
];

export const DEVICE_TYPE_FIELD_DEFINITIONS: ReadonlyArray<MetadataFieldDefinition> = [
  {
    key: "manufacturer",
    label: "Manufacturer",
    placeholder: "Cisco  or  {custom.manufacturer}",
    required: true,
    optionsField: "manufacturer",
  },
  {
    key: "role",
    label: "Role",
    placeholder: "Access Switch  or  {custom.role}",
    required: true,
    optionsField: "role",
    hint: "Checked against Nautobot and carried to the device for a later Add to Nautobot step.",
  },
  {
    key: "model",
    label: "Model (device type)",
    placeholder: "C9300-24T  or  {custom.model}",
    required: true,
  },
  {
    key: "height",
    label: "Height (U)",
    placeholder: "1  or  {custom.height}",
    required: true,
    hint: "Positive whole number. Defaults to 1 when left empty.",
  },
  {
    key: "platform",
    label: "Platform",
    placeholder: "Optional  or  {custom.platform}",
    required: false,
    optionsField: "platform",
    hint: "Optional, but Nautobot needs it to log in to the device.",
  },
];

export function fieldDefinitionsFor(
  metadataType: MetadataType,
): ReadonlyArray<MetadataFieldDefinition> {
  return metadataType === "location" ? LOCATION_FIELD_DEFINITIONS : DEVICE_TYPE_FIELD_DEFINITIONS;
}
