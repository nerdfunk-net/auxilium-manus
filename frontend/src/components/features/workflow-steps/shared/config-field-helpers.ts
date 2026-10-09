/**
 * Defensive readers for the heterogeneous `Record<string, unknown>` blobs that
 * workflow-step configs and template-editor params are stored as. Each returns a
 * well-typed value (or the fallback) no matter what the blob contains.
 */
export type ConfigRecord = Record<string, unknown>;

export function stringField(config: ConfigRecord, key: string, fallback = ""): string {
  const value = config[key];
  return typeof value === "string" ? value : fallback;
}

export function numberField(config: ConfigRecord, key: string, fallback: number): number {
  const value = config[key];
  return typeof value === "number" ? value : fallback;
}

export function boolField(config: ConfigRecord, key: string, fallback = false): boolean {
  const value = config[key];
  return typeof value === "boolean" ? value : fallback;
}

/** Number-or-string value as the string an `<Input type="number">` needs ("" if absent). */
export function numberInputField(config: ConfigRecord, key: string): string {
  const value = config[key];
  return typeof value === "number" ? String(value) : typeof value === "string" ? value : "";
}

/** String array rendered as a comma-separated string ("" if absent / not an array). */
export function joinedStringList(config: ConfigRecord, key: string): string {
  const value = config[key];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").join(", ")
    : "";
}
