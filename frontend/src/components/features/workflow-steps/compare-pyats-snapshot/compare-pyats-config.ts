export function excludeKeysFromConfig(config: Record<string, unknown>): string[] {
  return Array.isArray(config.exclude_keys)
    ? config.exclude_keys.filter((item): item is string => typeof item === "string")
    : [];
}

export function featuresFromConfig(config: Record<string, unknown>): string[] {
  return Array.isArray(config.features)
    ? config.features.filter((item): item is string => typeof item === "string")
    : [];
}

export function buildComparePyatsSnapshotConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    features: featuresFromConfig(config),
    source_step_node_id:
      typeof config.source_step_node_id === "string" ? config.source_step_node_id : "",
    parsed_output_key:
      typeof config.parsed_output_key === "string" ? config.parsed_output_key : "",
    exclude_keys: excludeKeysFromConfig(config),
    reference_location:
      config.reference_location === "git" || config.reference_location === "filesystem"
        ? config.reference_location
        : "filesystem",
    reference_subdirectory:
      typeof config.reference_subdirectory === "string"
        ? config.reference_subdirectory
        : "pyats-snapshots",
    git_repository_id:
      typeof config.git_repository_id === "number" ? config.git_repository_id : null,
    repository_subdirectory:
      typeof config.repository_subdirectory === "string" ? config.repository_subdirectory : "",
    pull_before_read: config.pull_before_read === true,
    filename_template:
      typeof config.filename_template === "string"
        ? config.filename_template
        : "{device.name}.pyats-snapshot.json",
    ...patch,
  };
}
