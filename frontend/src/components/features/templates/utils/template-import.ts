import type { TemplateVariableRecord } from "../types";
import {
  TEMPLATE_EXPORT_FORMAT,
  type TemplateExportFile,
  type TemplateExportPayload,
} from "../types/template-export";

export class TemplateImportParseError extends Error {}

function parseVariables(raw: unknown): Record<string, TemplateVariableRecord> {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return {};
  }
  const result: Record<string, TemplateVariableRecord> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value !== "object" || value === null) continue;
    const record = value as Record<string, unknown>;
    result[key] = {
      value: typeof record.value === "string" ? record.value : "",
      type: typeof record.type === "string" ? record.type : "custom",
    };
  }
  return result;
}

function parseStringArray(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is string => typeof item === "string");
}

export function parseTemplateExportPayload(
  raw: unknown,
): TemplateExportPayload {
  if (typeof raw !== "object" || raw === null) {
    throw new TemplateImportParseError(
      "File does not contain a valid JSON object.",
    );
  }
  const obj = raw as Record<string, unknown>;
  if (typeof obj.name !== "string" || !obj.name.trim()) {
    throw new TemplateImportParseError("Import file is missing a template name.");
  }
  return {
    name: obj.name.trim(),
    description: typeof obj.description === "string" ? obj.description : null,
    template_type:
      typeof obj.template_type === "string" && obj.template_type.trim()
        ? obj.template_type
        : "jinja2",
    category:
      typeof obj.category === "string" && obj.category.trim()
        ? obj.category
        : "netmiko",
    content: typeof obj.content === "string" ? obj.content : "",
    variables: parseVariables(obj.variables),
    pre_run_commands: parseStringArray(obj.pre_run_commands),
    pre_run_use_textfsm: Boolean(obj.pre_run_use_textfsm),
    nautobot_attributes: parseStringArray(obj.nautobot_attributes),
  };
}

export function parseTemplateExportFile(raw: unknown): TemplateExportFile {
  if (typeof raw !== "object" || raw === null) {
    throw new TemplateImportParseError(
      "File does not contain a valid JSON object.",
    );
  }
  const obj = raw as Record<string, unknown>;
  if (obj.export_format !== TEMPLATE_EXPORT_FORMAT) {
    throw new TemplateImportParseError(
      "Unrecognized template export file. Expected a file exported from this application.",
    );
  }
  const payload = parseTemplateExportPayload(obj);
  return {
    export_format: TEMPLATE_EXPORT_FORMAT,
    exported_at:
      typeof obj.exported_at === "string"
        ? obj.exported_at
        : new Date().toISOString(),
    ...payload,
  };
}
