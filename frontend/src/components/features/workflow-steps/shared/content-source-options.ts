export const CONTENT_SOURCE_OPTIONS = [
  {
    value: "upstream_output",
    label: "Upstream output (auto-detected)",
    hint: "Automatically resolved from the nearest content-producing upstream step.",
  },
  {
    value: "running_config",
    label: "Running configuration",
    hint: "Requires an upstream get-device-configs (or similar) step.",
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
  {
    value: "updated_content",
    label: "Updated content",
    hint: "Choose the update-content step that produced the edited config.",
  },
] as const;

export type ContentSource = (typeof CONTENT_SOURCE_OPTIONS)[number]["value"];
