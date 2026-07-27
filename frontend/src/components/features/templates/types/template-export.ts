import type { TemplateVariableRecord } from "../types";

export const TEMPLATE_EXPORT_FORMAT = "auxilium-template-v1" as const;

/** Portable template body used for standalone and workflow-embedded exports. */
export interface TemplateExportPayload {
  name: string;
  description: string | null;
  template_type: string;
  category: string;
  content: string;
  variables: Record<string, TemplateVariableRecord>;
  pre_run_commands: string[];
  pre_run_use_textfsm: boolean;
  nautobot_attributes: string[];
}

export interface TemplateExportFile extends TemplateExportPayload {
  export_format: typeof TEMPLATE_EXPORT_FORMAT;
  exported_at: string;
}
