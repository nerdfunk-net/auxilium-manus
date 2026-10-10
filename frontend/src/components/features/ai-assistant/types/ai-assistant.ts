export type AiProvider = "anthropic" | "gemini" | "openai_compat";

export type AiStatusReason = "ok" | "no_permission" | "disabled" | "not_configured";

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

/** A message in the panel; `error` is set on an assistant turn that failed. */
export interface DisplayMessage extends ChatMessage {
  id: string;
  error?: string;
}
