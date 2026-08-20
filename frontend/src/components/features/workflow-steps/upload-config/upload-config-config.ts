export const DEFAULT_SOCKET_TIMEOUT = 10;
export const MIN_SOCKET_TIMEOUT = 5;
export const MAX_SOCKET_TIMEOUT = 300;

export const UPLOAD_CONFIG_SOURCE_OPTIONS = [
  {
    value: "updated_content",
    label: "Updated content",
    hint: "Requires an upstream update-content step.",
  },
  {
    value: "running_config",
    label: "Running configuration",
    hint: "Requires an upstream Read Config or Get Device Configs step. No step picker needed — the most recent running config is used automatically.",
  },
  {
    value: "startup_config",
    label: "Startup configuration",
    hint: "Requires startup config on the device context.",
  },
  {
    value: "command_output",
    label: "Command output (specific step)",
    hint: "Choose the run-command step that produced the output.",
  },
  {
    value: "latest_command_output",
    label: "Latest command output",
    hint: "Uses the most recent command result on the device.",
  },
  {
    value: "rendered_template",
    label: "Rendered template",
    hint: "Choose the render-jinja-template step that produced the template.",
  },
  {
    value: "merged_content",
    label: "Merged content",
    hint: "Choose the merge-content step that combined multiple command outputs.",
  },
  {
    value: "comparison_diff",
    label: "Comparison diff",
    hint: "Choose the compare-data step that produced a unified diff on mismatch.",
  },
  {
    value: "filtered_output",
    label: "Filtered output",
    hint: "Choose the filter-output step that removed volatile fields.",
  },
  {
    value: "pyats_snapshot",
    label: "pyATS snapshot",
    hint: "Choose the get-pyats-snapshot step that produced the snapshot.",
  },
] as const;

export type ContentSource = (typeof UPLOAD_CONFIG_SOURCE_OPTIONS)[number]["value"];

const SOURCE_STEP_NOT_REQUIRED = new Set<ContentSource>([
  "running_config",
  "startup_config",
  "latest_command_output",
]);

const PARSED_OUTPUT_KEY_SOURCES = new Set<ContentSource>(["rendered_template", "pyats_snapshot"]);

interface SourceStepCopy {
  placeholder: string;
  missingStep: string;
  manualPlaceholder: string;
}

const SOURCE_STEP_COPY: Partial<Record<ContentSource, SourceStepCopy>> = {
  updated_content: {
    placeholder: "Choose update-content step…",
    missingStep: "Add an Update Content step to this workflow first.",
    manualPlaceholder: "update-content-3",
  },
  command_output: {
    placeholder: "Choose run-command step…",
    missingStep: "Add a Run Command step to this workflow first.",
    manualPlaceholder: "run-command-3",
  },
  rendered_template: {
    placeholder: "Choose render step…",
    missingStep: "Add a Render Jinja Template step to this workflow first.",
    manualPlaceholder: "render-jinja-template-3",
  },
  merged_content: {
    placeholder: "Choose merge-content step…",
    missingStep: "Add a Merge Content step to this workflow first.",
    manualPlaceholder: "merge-content-3",
  },
  comparison_diff: {
    placeholder: "Choose compare-data step…",
    missingStep: "Add a Compare Data step to this workflow first.",
    manualPlaceholder: "compare-data-3",
  },
  filtered_output: {
    placeholder: "Choose filter-output step…",
    missingStep: "Add a Filter Output step to this workflow first.",
    manualPlaceholder: "filter-output-3",
  },
  pyats_snapshot: {
    placeholder: "Choose get-pyats-snapshot step…",
    missingStep: "Add a Get Snapshot step to this workflow first.",
    manualPlaceholder: "get-pyats-snapshot-3",
  },
};

export function needsSourceStepNodeId(contentSource: ContentSource): boolean {
  return !SOURCE_STEP_NOT_REQUIRED.has(contentSource);
}

export function needsParsedOutputKey(contentSource: ContentSource): boolean {
  return PARSED_OUTPUT_KEY_SOURCES.has(contentSource);
}

export function sourceStepCopy(contentSource: ContentSource): SourceStepCopy {
  return (
    SOURCE_STEP_COPY[contentSource] ?? {
      placeholder: "Choose source step…",
      missingStep: "Add an upstream step producing this content first.",
      manualPlaceholder: "step-node-id",
    }
  );
}

export function buildUploadConfigConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    credential_reference:
      typeof config.credential_reference === "string" ? config.credential_reference : "",
    content_source: typeof config.content_source === "string" ? config.content_source : "updated_content",
    source_step_node_id:
      typeof config.source_step_node_id === "string" ? config.source_step_node_id : "",
    parsed_output_key:
      typeof config.parsed_output_key === "string" ? config.parsed_output_key : "",
    destination_filename:
      typeof config.destination_filename === "string" ? config.destination_filename : "",
    file_system: typeof config.file_system === "string" ? config.file_system : "",
    overwrite: config.overwrite === true,
    inline_transfer: config.inline_transfer === true,
    network_driver_override:
      typeof config.network_driver_override === "string" ? config.network_driver_override : "",
    socket_timeout:
      typeof config.socket_timeout === "number" && Number.isFinite(config.socket_timeout)
        ? config.socket_timeout
        : DEFAULT_SOCKET_TIMEOUT,
    ...patch,
  };
}
