/** Locations list + mode shared by the Nautobot steps that edit an object's locations
 * (`update-nautobot-vlan`, `update-nautobot-prefix`). */
export const LOCATIONS_KEY = "locations";
export const LOCATIONS_MODE_KEY = "locations_mode";

export const LOCATIONS_MODE_OPTIONS = [
  { value: "replace", label: "Replace – exact list" },
  { value: "add", label: "Add to current" },
  { value: "remove", label: "Remove from current" },
] as const;

export const DEFAULT_LOCATIONS_MODE = "replace";
export const BAD_MODE_PROBLEM = "locations_mode is not valid";

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
