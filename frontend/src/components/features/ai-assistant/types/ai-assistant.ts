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
  share_inventory_data: boolean;
  share_content_data: boolean;
  available_providers: AiProvider[];
  available_models: Record<string, AiModelOption[]>;
}

export interface AiSettingsUpdate {
  enabled?: boolean;
  provider?: AiProvider;
  model?: string;
  api_key?: string;
  clear_api_key?: boolean;
  share_inventory_data?: boolean;
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

export type AssistantContext = TemplateEditorContext;

export type ToolStatus = "running" | "done" | "error";

export interface ToolActivity {
  id: string;
  name: string;
  status: ToolStatus;
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

/** A message in the panel; `error` is set on an assistant turn that failed. */
export interface DisplayMessage extends ChatMessage {
  id: string;
  error?: string;
  tools?: ToolActivity[];
  proposal?: TemplateProposal;
}
