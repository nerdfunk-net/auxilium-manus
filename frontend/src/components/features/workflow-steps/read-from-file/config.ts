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

export const FORMAT_OPTIONS = [
  { value: "auto", label: "Auto (by extension)" },
  { value: "yaml", label: "YAML" },
  { value: "json", label: "JSON" },
] as const;

export type ReadFromFileSource = (typeof SOURCE_OPTIONS)[number]["value"];
export type ReadFromFileFormat = (typeof FORMAT_OPTIONS)[number]["value"];

const DEFAULT_DESTINATION_PATH = "data";

/**
 * Re-emit the whole normalized `read-from-file` config, then apply `patch`.
 * Fallbacks mirror `backend/workflow_steps/read_from_file/config.py::get_config()`.
 */
export function buildReadFromFileConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    source: config.source === "git" ? "git" : "filesystem",
    git_repository_id:
      typeof config.git_repository_id === "number" ? config.git_repository_id : null,
    path: typeof config.path === "string" ? config.path : "",
    format:
      config.format === "yaml" || config.format === "json" ? config.format : "auto",
    destination_path:
      typeof config.destination_path === "string" && config.destination_path.trim()
        ? config.destination_path
        : DEFAULT_DESTINATION_PATH,
    overwrite: config.overwrite === true,
    ...patch,
  };
}
