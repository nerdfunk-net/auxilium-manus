export const VLAN_ID_KEY = "vlan_id";
export const VID_KEY = "vid";
export const VLAN_GROUP_KEY = "vlan_group";
export const NAME_KEY = "name";
export const DESCRIPTION_KEY = "description";
export const STATUS_KEY = "status";
export const ROLE_KEY = "role";
export const LOCATIONS_KEY = "locations";
export const LOCATIONS_MODE_KEY = "locations_mode";

/** The fields the step can change; an empty one is left unchanged. */
export const UPDATE_FIELD_KEYS = [
  NAME_KEY,
  DESCRIPTION_KEY,
  STATUS_KEY,
  ROLE_KEY,
  LOCATIONS_KEY,
] as const;

export const LOCATIONS_MODE_OPTIONS = [
  { value: "replace", label: "Replace – exact list" },
  { value: "add", label: "Add to current" },
  { value: "remove", label: "Remove from current" },
] as const;

export const DEFAULT_LOCATIONS_MODE = "replace";

export const NO_VLAN_PROBLEM = "vlan_id or vid is not configured";
export const NO_FIELD_PROBLEM = "configure at least one field to update";
export const BAD_MODE_PROBLEM = "locations_mode is not valid";

/** The configuration problems the panel shows as warnings (empty = complete). */
export function configProblems(config: Record<string, unknown>): string[] {
  const text = (key: string) =>
    typeof config[key] === "string" ? (config[key] as string).trim() : "";
  const problems: string[] = [];
  if (!text(VLAN_ID_KEY) && !text(VID_KEY)) problems.push(NO_VLAN_PROBLEM);
  if (UPDATE_FIELD_KEYS.every((key) => !text(key))) problems.push(NO_FIELD_PROBLEM);
  if (!isValidLocationsMode(config)) problems.push(BAD_MODE_PROBLEM);
  return problems;
}

/** A missing or empty mode is fine (the step defaults to replace); any other value must be known. */
export function isValidLocationsMode(config: Record<string, unknown>): boolean {
  const mode = config[LOCATIONS_MODE_KEY];
  if (mode === undefined || mode === null || mode === "") return true;
  return LOCATIONS_MODE_OPTIONS.some((option) => option.value === mode);
}

/** The mode the select shows: the stored one, replace when none is stored, "" when it is invalid. */
export function locationsModeFromConfig(config: Record<string, unknown>): string {
  if (!isValidLocationsMode(config)) return "";
  const mode = config[LOCATIONS_MODE_KEY];
  return typeof mode === "string" && mode ? mode : DEFAULT_LOCATIONS_MODE;
}
