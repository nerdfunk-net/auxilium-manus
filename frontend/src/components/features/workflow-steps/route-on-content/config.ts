export const CONTENT_SOURCE_OPTIONS = [
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
    value: "filtered_output",
    label: "Filtered output",
    hint: "Choose the filter-output step that removed volatile fields.",
  },
  {
    value: "comparison_diff",
    label: "Comparison diff",
    hint: "Choose the compare-data step that produced the diff.",
  },
] as const;

export type ContentSource = (typeof CONTENT_SOURCE_OPTIONS)[number]["value"];

export const MATCH_MODE_OPTIONS = [
  { value: "fixed_text", label: "Fixed text", hint: "Literal substring search." },
  { value: "regex", label: "Regular expression", hint: "Python-style regular expression." },
] as const;

export type MatchMode = (typeof MATCH_MODE_OPTIONS)[number]["value"];

export interface RouteOnContentConfig {
  content_source: ContentSource;
  source_step_node_id: string;
  parsed_output_key: string;
  match_mode: MatchMode;
  pattern: string;
  case_sensitive: boolean;
  multiline: boolean;
}

export const DEFAULT_ROUTE_ON_CONTENT_CONFIG: RouteOnContentConfig = {
  content_source: "running_config",
  source_step_node_id: "",
  parsed_output_key: "",
  match_mode: "fixed_text",
  pattern: "",
  case_sensitive: false,
  multiline: false,
};

const VALID_CONTENT_SOURCES = new Set<string>(
  CONTENT_SOURCE_OPTIONS.map((option) => option.value),
);
const VALID_MATCH_MODES = new Set<string>(MATCH_MODE_OPTIONS.map((option) => option.value));

/** content_source values whose text lives on a specific upstream step, so
 * source_step_node_id must be set. running_config/startup_config read
 * directly off the device context; latest_command_output auto-picks the
 * most recent command result — neither needs a step reference. */
const SOURCE_STEP_REQUIRED = new Set<ContentSource>([
  "command_output",
  "rendered_template",
  "merged_content",
  "filtered_output",
  "comparison_diff",
]);

export function contentSourceRequiresStepNodeId(contentSource: ContentSource): boolean {
  return SOURCE_STEP_REQUIRED.has(contentSource);
}

export function parseRouteOnContentConfig(
  config: Record<string, unknown>,
): RouteOnContentConfig {
  return {
    content_source:
      typeof config.content_source === "string" &&
      VALID_CONTENT_SOURCES.has(config.content_source)
        ? (config.content_source as ContentSource)
        : DEFAULT_ROUTE_ON_CONTENT_CONFIG.content_source,
    source_step_node_id:
      typeof config.source_step_node_id === "string" ? config.source_step_node_id : "",
    parsed_output_key:
      typeof config.parsed_output_key === "string" ? config.parsed_output_key : "",
    match_mode:
      typeof config.match_mode === "string" && VALID_MATCH_MODES.has(config.match_mode)
        ? (config.match_mode as MatchMode)
        : DEFAULT_ROUTE_ON_CONTENT_CONFIG.match_mode,
    pattern: typeof config.pattern === "string" ? config.pattern : "",
    case_sensitive: config.case_sensitive === true,
    multiline: config.multiline === true,
  };
}

export function buildRouteOnContentConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    ...parseRouteOnContentConfig(config),
    ...patch,
  };
}
