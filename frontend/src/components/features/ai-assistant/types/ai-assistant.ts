import type { ConditionTree } from "@/components/features/inventory/types/device-selector";
import type { ReportSection } from "@/components/features/reports/types/report-definition";
import type { ReportQuerySpec } from "@/components/features/reports/types/report-query";

export type AiProvider = "anthropic" | "gemini" | "openai_compat";

export type AiStatusReason =
  | "ok"
  | "no_permission"
  | "disabled"
  | "not_configured"
  | "operator_disabled"
  | "provider_not_allowed";

export interface AiStatus {
  available: boolean;
  reason: AiStatusReason;
}

export interface AiModelOption {
  id: string;
  label: string;
  description: string;
}

/** The API key is write-only: the server only ever reports `api_key_set`. */
export interface AiSettings {
  enabled: boolean;
  provider: AiProvider;
  model: string;
  base_url: string | null;
  api_key_set: boolean;
  /** Ready to use: a key (hosted providers) or a base URL + model (OpenAI-compatible). */
  configured: boolean;
  share_inventory_data: boolean;
  /** Finer opt-ins inside inventory data; only effective while share_inventory_data is on. */
  share_device_addresses: boolean;
  share_custom_fields: boolean;
  share_config_context: boolean;
  share_content_data: boolean;
  /** Values collected by Store for Report steps (query results, snapshots). */
  share_report_data: boolean;
  /** The user's own token cap for one question; null = the default applies. */
  max_turn_tokens: number | null;
  default_turn_tokens: number;
  available_providers: AiProvider[];
  available_models: Record<string, AiModelOption[]>;
  /** What the administrator allows (AI_ASSISTANT_ENABLED / AI_ALLOWED_PROVIDERS / AI_ALLOWED_DATA). */
  operator_enabled?: boolean;
  operator_providers?: AiProvider[];
  operator_data?: string[];
}

export interface AiSettingsUpdate {
  enabled?: boolean;
  provider?: AiProvider;
  model?: string;
  /** OpenAI-compatible only; an empty string clears it. */
  base_url?: string;
  api_key?: string;
  clear_api_key?: boolean;
  share_inventory_data?: boolean;
  share_device_addresses?: boolean;
  share_custom_fields?: boolean;
  share_config_context?: boolean;
  share_content_data?: boolean;
  share_report_data?: boolean;
  /** 0 = back to the default. */
  max_turn_tokens?: number;
}

export interface AiConnectionTestResult {
  ok: boolean;
  code?: string;
  message?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

/** One variable row of the template editor, as sent to the server. */
export interface EditorVariableContext {
  name: string;
  type: string;
  /** Empty for device/run variables: their values are never sent. */
  value: string;
  is_auto: boolean;
}

/** Current (possibly unsaved) template editor state, sent with every chat turn. */
export interface TemplateEditorContext {
  surface: "template_editor";
  name: string;
  description: string | null;
  template_type: string;
  /** "report": rendered once per generated report into Markdown, not once per device. */
  category?: "netmiko" | "report";
  content: string;
  variables: EditorVariableContext[];
}

/** The workflow builder canvas in its persisted shape (the server builds the model's view). */
export interface WorkflowCanvasContext {
  surface: "workflow_editor";
  name: string;
  canvas_nodes: Record<string, unknown>[];
  canvas_edges: Record<string, unknown>[];
  canvas_groups: Record<string, unknown>[];
  static_attributes: Record<string, unknown>[];
}

/** The runs page: the run (if any) the user has open. Read-only surface. */
export interface RunViewerContext {
  surface: "run_viewer";
  run_id: number | null;
}

/** The inventory page: its Nautobot source and the filter currently in the builder. */
export interface InventoryContext {
  surface: "inventory";
  source_id: string;
  /** The builder's (possibly unsaved) filter, so "also exclude lab devices" can refine it. */
  filter_tree?: ConditionTree;
}

/** The reports page: the report source it uses. Read-only surface. */
export interface ReportsContext {
  surface: "reports";
  source_id: string;
}

/** Ask the Net: free questions about the network. No client state; the server decides what it reads. */
export interface GeneralContext {
  surface: "general";
}

export type AssistantContext =
  | TemplateEditorContext
  | WorkflowCanvasContext
  | RunViewerContext
  | InventoryContext
  | ReportsContext
  | GeneralContext;

export type ToolStatus = "running" | "done" | "error";

export interface ToolActivity {
  id: string;
  name: string;
  status: ToolStatus;
  /** The result was cut; the answer may rest on partial data. */
  truncated?: boolean;
  /** Opt-in data classes the result had to leave out (server names, e.g. `content_data`). */
  withheld?: string[];
}

export type ProposalState = "pending" | "applied" | "rejected";

/** A change the assistant proposes. Never applied by itself; the user applies or rejects it. */
export interface TemplateProposal {
  kind: "template";
  content: string;
  summary: string;
  warnings: string[];
  /** Editor content when the turn started: lets the card warn if the buffer changed since. */
  baseContent: string;
  state: ProposalState;
}

export interface WorkflowChangeNode {
  id: string;
  kind: string | null;
  title: string;
  /** Pretty-printed step config with secret values masked (added steps only). */
  config?: string;
}

export interface WorkflowChangedNode extends WorkflowChangeNode {
  fields: string[];
  /** Pretty-printed step config before / after (for a line diff). */
  before: string;
  after: string;
}

export interface WorkflowChangeEdge {
  from: string;
  outcome: string;
  to: string;
}

/** One run input as shown in a change row (secret-named defaults arrive as a length only). */
export interface StaticAttributeBrief {
  type?: string;
  ref_kind?: string | null;
  default?: unknown;
  required?: boolean;
}

export interface StaticAttributeChange {
  name: string;
  before: StaticAttributeBrief | null;
  after: StaticAttributeBrief | null;
}

export interface WorkflowChanges {
  nodes_added: WorkflowChangeNode[];
  nodes_removed: WorkflowChangeNode[];
  nodes_changed: WorkflowChangedNode[];
  edges_added: WorkflowChangeEdge[];
  edges_removed: WorkflowChangeEdge[];
  static_attributes_changed: boolean;
  static_attributes?: StaticAttributeChange[];
}

export interface WorkflowProposalWarning {
  node_id: string | null;
  code: string;
  message: string;
}

/** A validated workflow change. Applying loads it into the builder as unsaved state. */
export interface WorkflowProposal {
  kind: "workflow";
  summary: string;
  canvas_nodes: Record<string, unknown>[];
  canvas_edges: Record<string, unknown>[];
  canvas_groups: Record<string, unknown>[];
  static_attributes: Record<string, unknown>[];
  changes: WorkflowChanges;
  warnings: WorkflowProposalWarning[];
  /** Fingerprint of the canvas when the turn started (detects edits made meanwhile). */
  baseFingerprint: string;
  state: ProposalState;
}

/** A checked report query. Applying loads it into the Explore query builder (nothing runs or is saved). */
export interface QueryProposal {
  kind: "query";
  summary: string;
  query: ReportQuerySpec;
  state: ProposalState;
}

/** A drafted report. Applying opens the report editor prefilled; nothing is saved until the user saves. */
export interface ReportOutlineProposal {
  kind: "report_outline";
  summary: string;
  name: string;
  description: string | null;
  sections: ReportSection[];
  state: ProposalState;
}

/** New text for one section of a saved report. Applying opens the editor with it filled in. */
export interface SectionTextProposal {
  kind: "section_text";
  summary: string;
  reportId: number;
  sectionId: string;
  sectionTitle: string;
  text: string;
  state: ProposalState;
}

/** A checked inventory filter. Applying loads it into the builder as unsaved state; the user saves. */
export interface InventoryProposal {
  kind: "inventory";
  summary: string;
  tree: ConditionTree;
  /** How many devices the filter selected when it was checked; null when the user has not
   * shared that kind of data with the assistant (the builder shows the count). */
  totalCount: number | null;
  warnings: string[];
  /** Fingerprint of the builder's filter when the turn started (detects edits made meanwhile). */
  baseFingerprint: string;
  state: ProposalState;
}

/** How the output of a proposed device command is turned into structured data after the run. */
export type CommandParser = "none" | "textfsm" | "genie";

export const COMMAND_PARSER_LABELS: Record<CommandParser, string> = {
  none: "none",
  textfsm: "TextFSM",
  genie: "Genie",
};

/** A command whose output could not be parsed; the text is fixed by the server. */
export interface CommandParseError {
  command: string;
  error: string;
}

/** What a confirmed device command returned (redacted, capped). */
export interface DeviceCommandResult {
  success: boolean;
  error: string | null;
  deviceName: string;
  commands: string[];
  output: string;
  truncated: boolean;
  /** Lets the assistant read the output (fetch_slice); null when it could not be stored. */
  handle: string | null;
  /** The parser the card showed (signed in the token). The raw output is kept either way. */
  parser: CommandParser;
  /** Handle of the parsed rows (query_result / fetch_slice); null when nothing parsed. */
  parsedHandle: string | null;
  /** The parsed data as indented JSON (cut), for the card. */
  parsedText: string;
  parseErrors: CommandParseError[];
}

/**
 * Read-only `show` commands the assistant wants run on one device. Nothing runs until the user
 * picks an SSH login and clicks Run; the token (signed by the server) carries the device and the
 * commands, so what runs is what the card shows.
 */
export interface DeviceCommandProposal {
  kind: "device_command";
  summary: string;
  token: string;
  /** Unix seconds; the server refuses the token after this. */
  expiresAt: number;
  device: { id: string; name: string; host: string; platform: string | null };
  commands: string[];
  /** Parser to run on the output after the command; signed in the token, so fixed here. */
  parser: CommandParser;
  /** False when the inventory's platform names no SSH driver: the user must choose one. */
  driverKnown: boolean;
  /** The device types the user may choose from (a closed list from the server). */
  driverChoices: string[];
  result?: DeviceCommandResult;
  state: ProposalState;
}

/**
 * A backed-up device configuration the user can download. The server stored the (redacted) text
 * behind `handle`; the card carries no text, the download reads it from the server.
 */
export interface ConfigDownloadProposal {
  kind: "config_download";
  summary: string;
  /** The handle of the stored text (`res_` + 12 hex digits). */
  handle: string;
  device: string;
  /** "running" or "startup" (shown as text only). */
  configKind: string;
  repository: string;
  /** ISO 8601 time of the backup's last commit, when known. */
  committedAt: string | null;
  sizeChars: number;
  lineCount: number;
  /** True when the file was longer than the server's limit and only its start is stored. */
  partial: boolean;
  state: ProposalState;
}

/** The run a confirmed workflow proposal started. */
export interface WorkflowRunResult {
  runId: number;
  workflowId: number;
}

/** A device the run will act on: an inventory device, or an address the user typed in the chat. */
export interface WorkflowRunDevice {
  name: string;
  ip: string;
  inInventory: boolean;
}

/**
 * A released workflow the assistant wants run, with the inputs and devices it chose. Nothing starts
 * until the user clicks Run; the token (signed by the server) carries all of it, so what starts is
 * what the card shows.
 */
export interface WorkflowRunProposal {
  kind: "workflow_run";
  summary: string;
  token: string;
  /** Unix seconds; the server refuses the token after this. */
  expiresAt: number;
  workflow: { id: number; name: string };
  inputs: Record<string, string | number | boolean>;
  devices: WorkflowRunDevice[];
  /** Credential inputs the user fills in on the card (their own credential); never the model. */
  credentialInputs: string[];
  /** Device types the user may choose for an address outside the inventory (closed list). */
  driverChoices: string[];
  result?: WorkflowRunResult;
  state: ProposalState;
}

export type AssistantProposal =
  | TemplateProposal
  | WorkflowProposal
  | QueryProposal
  | ReportOutlineProposal
  | SectionTextProposal
  | InventoryProposal
  | DeviceCommandProposal
  | ConfigDownloadProposal
  | WorkflowRunProposal;

/** A message in the panel; `error` is set on an assistant turn that failed. */
export interface DisplayMessage extends ChatMessage {
  id: string;
  error?: string;
  tools?: ToolActivity[];
  proposal?: AssistantProposal;
  /** A proposal from a resumed conversation: only its summary survives, it can't be applied. */
  savedProposal?: SavedProposal;
}

export type AssistantSurface =
  | "template_editor"
  | "workflow_editor"
  | "run_viewer"
  | "inventory"
  | "reports"
  | "general";

/** What a panel needs to save and list conversations: its surface and subject (for example a workflow id). */
export interface ConversationScope {
  surface: AssistantSurface;
  subjectKey: string;
}

export interface SavedProposal {
  kind:
    | "template"
    | "workflow"
    | "query"
    | "report_outline"
    | "section_text"
    | "inventory"
    | "device_command"
    | "config_download"
    | "workflow_run";
  summary: string;
}

export interface SavedToolChip {
  id: string;
  name: string;
  status: ToolStatus;
  truncated: boolean;
  withheld: string[];
}

/** A message as the server stores it (redacted; proposals reduced to kind and summary). */
export interface SavedMessage {
  role: "user" | "assistant";
  content: string;
  error?: string | null;
  tools: SavedToolChip[];
  proposal?: SavedProposal | null;
}

export interface SavedConversationSummary {
  id: number;
  surface: AssistantSurface;
  subject_key: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface SavedConversation extends SavedConversationSummary {
  messages: SavedMessage[];
}

/** Global proxy for all AI provider traffic (administrator only). No password ever appears here. */
export interface AiProxySettings {
  enabled: boolean;
  url: string;
  credential_id: number | null;
  credential_name: string | null;
  bypass_hosts: string[];
  configured: boolean;
}

export interface AiProxySettingsUpdate {
  enabled: boolean;
  url: string;
  credential_id: number | null;
  bypass_hosts: string[];
}

/** One condition of a glossary filter (same shape as the inventory assistant's filter). */
export interface GlossaryCondition {
  field: string;
  operator: string;
  value: string;
}

export interface GlossaryGroup {
  logic: "AND" | "OR";
  negate: boolean;
  conditions: GlossaryCondition[];
}

export interface GlossaryFilter {
  logic: "AND" | "OR";
  conditions: GlossaryCondition[];
  groups: GlossaryGroup[];
}

export type GlossaryKind = "inventory_filter" | "workflow_step";

interface GlossaryTermBase {
  id: number;
  term: string;
  aliases: string[];
  /** For administrators only; never sent to the model. */
  note: string | null;
  warnings: string[];
}

/** A word ("core") the inventory assistant expands into a filter. */
export interface InventoryGlossaryTerm extends GlossaryTermBase {
  kind: "inventory_filter";
  payload: GlossaryFilter;
}

/** A word ("Get from GIT") the workflow assistant maps to one registry step. */
export interface StepAliasTerm extends GlossaryTermBase {
  kind: "workflow_step";
  payload: { step_id: string };
}

export type GlossaryTerm = InventoryGlossaryTerm | StepAliasTerm;

interface GlossaryInputBase {
  term: string;
  aliases: string[];
  note: string | null;
}

export interface InventoryGlossaryInput extends GlossaryInputBase {
  kind: "inventory_filter";
  filter: GlossaryFilter;
  /** Nautobot source the values are checked against. */
  source_id: string;
}

export interface StepAliasInput extends GlossaryInputBase {
  kind: "workflow_step";
  step_id: string;
}

export type GlossaryTermInput = InventoryGlossaryInput | StepAliasInput;

export interface GlossaryList {
  items: GlossaryTerm[];
  total: number;
}
