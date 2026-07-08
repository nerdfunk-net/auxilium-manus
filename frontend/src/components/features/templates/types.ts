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

export interface Template {
  id: number;
  name: string;
  source: string;
  template_type: string;
  category: string;
  description: string | null;
  content: string;
  variables: Record<string, TemplateVariableRecord>;
  pre_run_commands: string[];
  pre_run_use_textfsm: boolean;
  nautobot_attributes: string[];
  credential_id: number | null;
  created_by: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface TemplateCreatePayload {
  name: string;
  description?: string | null;
  template_type: string;
  category: string;
  content: string;
  variables: Record<string, TemplateVariableRecord>;
  pre_run_commands: string[];
  pre_run_use_textfsm: boolean;
  nautobot_attributes: string[];
  credential_id?: number | null;
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
