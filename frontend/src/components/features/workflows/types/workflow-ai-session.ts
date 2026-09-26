export interface WorkflowAiSession {
  active: boolean;
  expires_at: string | null;
  enabled_by_username: string | null;
  workflow_updated_at: string;
}

export interface WorkflowAiSessionEnableRequest {
  ttl_minutes?: number;
}
