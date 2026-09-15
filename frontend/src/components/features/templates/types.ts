export type TemplateType = "jinja2" | "text" | "textfsm";

export interface TemplateVariableRecord {
  value: string;
  type: string;
}

export interface TemplateListItem {
  id: number;
  name: string;
  source: string;
  template_type: string;
  category: string;
  description: string | null;
  created_by: string | null;
  updated_at: string | null;
}

export interface TemplateListResponse {
  templates: TemplateListItem[];
  total: number;
}

/** Which Batfish question a query targets (matches pybatfish's own answer-type names). */
export type BatfishQueryQuestion = "routes" | "reachability" | "testFilters";

/**
 * The 5 "facts" questions -- unlike the 3 above, these mirror a real
 * per-device workflow step (Extract Facts / Get OSPF Facts / Get BGP Facts /
 * Batfish Node Properties / Batfish Interface Properties) and populate the
 * real `parsed.<output_key>` namespace instead of the flat, preview-only
 * `batfish` variable. See `isFactsQuestion` in
 * `hooks/use-template-editor-batfish.ts` and the "Batfish (per-device steps
 * only)" section of the Jinja help dialog.
 */
export type BatfishFactsQuestion =
  | "extractFacts"
  | "ospfFacts"
  | "bgpFacts"
  | "nodeProperties"
  | "interfaceProperties";

/**
 * Editor-local question selector: the 3 typed questions above, the 5 facts
 * questions, plus "generic" -- a sentinel for the "Custom Question..."
 * picker entry, which lets the ad-hoc query target any question in the
 * backend's GENERIC_QUESTION_ALLOWLIST (services/batfish/query_helpers.py)
 * via `generic_question_name` below rather than a fixed union member.
 */
export type BatfishEditorQuestion = BatfishQueryQuestion | BatfishFactsQuestion | "generic";

/**
 * Persisted Batfish query definition for the template editor's preview
 * `batfish` variable. Only the query definition round-trips with the
 * template — never the fetched answer itself, mirroring how parsed_config/
 * command results also aren't saved with the template.
 */
export interface BatfishQueryConfig {
  enabled: boolean;
  source_id: string | null;
  network: string | null;
  snapshot: string | null;
  question: BatfishEditorQuestion | null;
  /** The actual Batfish question name when `question === "generic"`. */
  generic_question_name: string | null;
  params: Record<string, unknown>;
}

/** Response from an ad-hoc POST sources/batfish/{source_id}/query/* call. */
export interface BatfishQueryResult {
  success: boolean;
  // A plain string, not BatfishQueryQuestion -- a generic query's response
  // carries whatever question name was actually run, not one of the 3 typed
  // ones (matches the backend's BatfishQueryResponse.question widening).
  question: string;
  network: string;
  snapshot: string;
  rows: unknown[];
  reachable?: boolean | null;
  action?: string | null;
  error?: string | null;
  /**
   * Populated only by the 5 `BatfishFactsQuestion` types:
   * `{node_name: <that node's parsed payload>}` -- the exact shape
   * `device.parsed[output_key]["parsed"]` holds for one device at real
   * workflow runtime. `rows` stays empty for these; see
   * `BatfishFactsQuestion`.
   */
  facts_by_node?: Record<string, unknown> | null;
}

export interface Template {
  id: number;
  name: string;
  source: string;
  template_type: string;
  category: string;
  description: string | null;
  /** Free-form Markdown wiki notes, edited inline in the template editor. */
  notes: string | null;
  content: string;
  variables: Record<string, TemplateVariableRecord>;
  pre_run_commands: string[];
  pre_run_use_textfsm: boolean;
  nautobot_attributes: string[];
  credential_id: number | null;
  batfish_config: BatfishQueryConfig | null;
  created_by: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface TemplateCreatePayload {
  name: string;
  description?: string | null;
  notes?: string | null;
  template_type: string;
  category: string;
  content: string;
  variables: Record<string, TemplateVariableRecord>;
  pre_run_commands: string[];
  pre_run_use_textfsm: boolean;
  nautobot_attributes: string[];
  credential_id?: number | null;
  batfish_config?: BatfishQueryConfig | null;
}

export type TemplateUpdatePayload = Partial<TemplateCreatePayload>;

export interface TemplateRenderResponse {
  rendered_content: string;
  variables_used: string[];
  warnings: string[];
}

/** A variable row shown in the editor's variables panel. */
export interface EditorVariable {
  id: string;
  name: string;
  value: string;
  type: string;
  isAutoFilled: boolean;
  description?: string;
}

/** One executed command, mirroring the workflow step's command namespace. */
export interface CommandEntry {
  node_id: string;
  name: string;
  success: boolean;
  raw: string;
  parsed: unknown;
}

/** Response from POST netmiko/get-configs, mirroring parse-cisco-config's entry. */
export interface GetConfigsResponse {
  success: boolean;
  parsed: unknown;
  error: string | null;
}

export interface DeviceSummary {
  id: string;
  name: string | null;
  primary_ip4: string | null;
  platform: string | null;
  network_driver: string | null;
}

export interface StoredCredential {
  id: number;
  name: string;
  username: string;
  type: string;
}

export interface NautobotSourceOption {
  sourceId: string;
}
