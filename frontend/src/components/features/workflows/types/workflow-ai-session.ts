export interface WorkflowAiSession {
  active: boolean;
  expires_at: string | null;
  enabled_by_username: string | null;
  workflow_updated_at: string;
  /** Things that would run the canvas unattended; AI canvas writes are refused while any exist. */
  unattended_triggers?: string[];
}

export interface WorkflowAiSessionEnableRequest {
  ttl_minutes?: number;
}
