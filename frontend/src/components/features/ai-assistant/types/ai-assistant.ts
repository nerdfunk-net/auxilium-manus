export type AiProvider = "anthropic" | "gemini" | "openai_compat";

export type AiStatusReason =
  "ok" | "no_permission" | "disabled" | "not_configured";

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
  available_providers: AiProvider[];
  available_models: Record<string, AiModelOption[]>;
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

/** The inventory page: the Nautobot source it uses. Read-only surface. */
export interface InventoryContext {
  surface: "inventory";
  source_id: string;
}

export type AssistantContext =
  | TemplateEditorContext
  | WorkflowCanvasContext
  | RunViewerContext
  | InventoryContext;

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

export interface WorkflowChanges {
  nodes_added: WorkflowChangeNode[];
  nodes_removed: WorkflowChangeNode[];
  nodes_changed: WorkflowChangedNode[];
  edges_added: WorkflowChangeEdge[];
  edges_removed: WorkflowChangeEdge[];
  static_attributes_changed: boolean;
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

export type AssistantProposal = TemplateProposal | WorkflowProposal;

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
  "template_editor" | "workflow_editor" | "run_viewer" | "inventory";

/** What a panel needs to save and list conversations: its surface and subject (for example a workflow id). */
export interface ConversationScope {
  surface: AssistantSurface;
  subjectKey: string;
}

export interface SavedProposal {
  kind: "template" | "workflow";
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
