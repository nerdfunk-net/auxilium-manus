export const SOURCE_OPTIONS = [
  {
    value: "filesystem",
    label: "Filesystem",
    hint: "Read from the default export directory (Settings → General).",
  },
  {
    value: "git",
    label: "Git repository",
    hint: "Read from a repository configured under Settings → Git Repositories.",
  },
] as const;

export const MATCH_MODE_OPTIONS = [
  {
    value: "match",
    label: "Match (equal)",
    hint: "The device value must equal the key of the row.",
  },
  {
    value: "contains",
    label: "Contains",
    hint: "The device value must contain the key of the row.",
  },
] as const;

export type EnrichAttributesSource = (typeof SOURCE_OPTIONS)[number]["value"];
export type EnrichAttributesMatchMode = (typeof MATCH_MODE_OPTIONS)[number]["value"];

const DEFAULT_DESTINATION_PATH = "data";
const DEFAULT_DELIMITER = ";";

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * Re-emit the whole normalized `enrich-attributes` config, then apply `patch`.
 * Fallbacks mirror `backend/workflow_steps/enrich_attributes/config.py::get_config()`.
 */
export function buildEnrichAttributesConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    source: config.source === "git" ? "git" : "filesystem",
    git_repository_id:
      typeof config.git_repository_id === "number" ? config.git_repository_id : null,
    allow_stale_repository: config.allow_stale_repository === true,
    path: text(config.path),
    delimiter: text(config.delimiter) !== "" ? text(config.delimiter) : DEFAULT_DELIMITER,
    key_column: text(config.key_column),
    device_attribute_path: text(config.device_attribute_path),
    match_mode: config.match_mode === "contains" ? "contains" : "match",
    case_insensitive: config.case_insensitive === true,
    destination_path: text(config.destination_path).trim()
      ? text(config.destination_path)
      : DEFAULT_DESTINATION_PATH,
    overwrite: config.overwrite === true,
    ...patch,
  };
}
