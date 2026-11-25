import {
  BAD_MODE_PROBLEM,
  LOCATIONS_KEY,
  LOCATIONS_MODE_KEY,
  isValidLocationsMode,
} from "../shared/nautobot-locations";

export const PREFIX_ID_KEY = "prefix_id";
export const PREFIX_KEY = "prefix";
export const NAMESPACE_KEY = "namespace";
export const DESCRIPTION_KEY = "description";
export const STATUS_KEY = "status";
export const ROLE_KEY = "role";
export const PREFIXES_FROM_INTERFACES_KEY = "prefixes_from_interfaces";
export const DRY_RUN_KEY = "dry_run";

/** The fields the step can change; an empty one is left unchanged. */
export const UPDATE_FIELD_KEYS = [
  DESCRIPTION_KEY,
  STATUS_KEY,
  ROLE_KEY,
  LOCATIONS_KEY,
] as const;



export const NO_PREFIX_PROBLEM = "prefix_id or prefix is not configured";
export const NO_FIELD_PROBLEM = "configure at least one field to update";
export const INTERFACE_CONFLICT_PROBLEM =
  "Prefixes from interfaces only adds the device's location; clear the other fields";

/** The keys the "prefixes from interfaces" mode refuses (the step fails when one is set). */
export const INTERFACE_MODE_REFUSED_KEYS = [
  PREFIX_ID_KEY,
  PREFIX_KEY,
  NAMESPACE_KEY,
  ...UPDATE_FIELD_KEYS,
] as const;

/** The config patch that switches the mode on: the refused keys are cleared, locations_mode is add. */
export function interfaceModeEnabledPatch(): Record<string, unknown> {
  const cleared = Object.fromEntries(
    INTERFACE_MODE_REFUSED_KEYS.map((key) => [key, ""]),
  );
  return {
    ...cleared,
    [LOCATIONS_MODE_KEY]: "add",
    [PREFIXES_FROM_INTERFACES_KEY]: true,
  };
}

/** True for a stored true / "true" (the step parses both). */
export function isFromInterfaces(config: Record<string, unknown>): boolean {
  const value = config[PREFIXES_FROM_INTERFACES_KEY];
  return (
    value === true ||
    (typeof value === "string" && value.trim().toLowerCase() === "true")
  );
}

/** The configuration problems the panel shows as warnings (empty = complete). */
export function configProblems(config: Record<string, unknown>): string[] {
  const text = (key: string) =>
    typeof config[key] === "string" ? (config[key] as string).trim() : "";
  const problems: string[] = [];
  if (isFromInterfaces(config)) {
    if (INTERFACE_MODE_REFUSED_KEYS.some((key) => text(key))) {
      problems.push(INTERFACE_CONFLICT_PROBLEM);
    }
    return problems;
  }
  if (!text(PREFIX_ID_KEY) && !text(PREFIX_KEY))
    problems.push(NO_PREFIX_PROBLEM);
  if (UPDATE_FIELD_KEYS.every((key) => !text(key)))
    problems.push(NO_FIELD_PROBLEM);
  if (!isValidLocationsMode(config)) problems.push(BAD_MODE_PROBLEM);
  return problems;
}


