import type { Template, TemplateCreatePayload } from "../types";
import {
  TEMPLATE_EXPORT_FORMAT,
  type TemplateExportFile,
  type TemplateExportPayload,
} from "../types/template-export";

export function slugifyTemplateName(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "template";
}

export function templateToExportPayload(
  template: Pick<
    Template,
    | "name"
    | "description"
    | "template_type"
    | "category"
    | "content"
    | "variables"
    | "pre_run_commands"
    | "pre_run_use_textfsm"
    | "nautobot_attributes"
  >,
): TemplateExportPayload {
  return {
    name: template.name,
    description: template.description,
    template_type: template.template_type,
    category: template.category,
    content: template.content ?? "",
    variables: template.variables ?? {},
    pre_run_commands: template.pre_run_commands ?? [],
    pre_run_use_textfsm: Boolean(template.pre_run_use_textfsm),
    nautobot_attributes: template.nautobot_attributes ?? [],
  };
}

export function buildTemplateExportFile(
  template: Parameters<typeof templateToExportPayload>[0],
): TemplateExportFile {
  return {
    export_format: TEMPLATE_EXPORT_FORMAT,
    exported_at: new Date().toISOString(),
    ...templateToExportPayload(template),
  };
}

export function templateExportToCreatePayload(
  payload: TemplateExportPayload,
): TemplateCreatePayload {
  return {
    name: payload.name,
    description: payload.description,
    template_type: payload.template_type,
    category: payload.category,
    content: payload.content,
    variables: payload.variables,
    pre_run_commands: payload.pre_run_commands,
    pre_run_use_textfsm: payload.pre_run_use_textfsm,
    nautobot_attributes: payload.nautobot_attributes,
    credential_id: null,
  };
}

export function downloadTemplateExportFile(file: TemplateExportFile): void {
  const blob = new Blob([JSON.stringify(file, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${slugifyTemplateName(file.name)}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
