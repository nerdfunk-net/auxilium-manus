import type { Credential } from "@/components/features/settings/credentials/types";
import type { Template } from "@/components/features/templates/types";
import { templateToExportPayload } from "@/components/features/templates/utils/template-export";

import type {
  WorkflowExportCredentialRef,
  WorkflowExportTemplate,
} from "../types/workflow-export";

export function slugifyWorkflowName(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "workflow";
}

/**
 * Collect unique non-empty credential_reference values from canvas node
 * pluginConfig blobs.
 */
export function collectCredentialReferencesFromCanvas(
  canvasNodes: Record<string, unknown>[],
): string[] {
  const names = new Set<string>();

  for (const node of canvasNodes) {
    const data = node.data;
    if (typeof data !== "object" || data === null) continue;
    const pluginConfig = (data as Record<string, unknown>).pluginConfig;
    if (typeof pluginConfig !== "object" || pluginConfig === null) continue;
    const ref = (pluginConfig as Record<string, unknown>).credential_reference;
    if (typeof ref !== "string") continue;
    const trimmed = ref.trim();
    if (trimmed) names.add(trimmed);
  }

  return [...names].sort();
}

/**
 * Collect unique numeric template_id values from canvas node pluginConfig blobs.
 */
export function collectTemplateIdsFromCanvas(
  canvasNodes: Record<string, unknown>[],
): number[] {
  const ids = new Set<number>();

  for (const node of canvasNodes) {
    const data = node.data;
    if (typeof data !== "object" || data === null) continue;
    const pluginConfig = (data as Record<string, unknown>).pluginConfig;
    if (typeof pluginConfig !== "object" || pluginConfig === null) continue;
    const raw = (pluginConfig as Record<string, unknown>).template_id;
    if (raw === null || raw === undefined || raw === "") continue;
    const id = typeof raw === "number" ? raw : Number(raw);
    if (Number.isInteger(id) && id > 0) ids.add(id);
  }

  return [...ids].sort((a, b) => a - b);
}

/**
 * Build the export sidecar for credential references resolved against the
 * exporter's visible vault. Unresolved names are emitted as private with a
 * null owner so import forces a remap.
 */
export function buildCredentialExportReferences(
  credentialNames: string[],
  credentials: Credential[],
): WorkflowExportCredentialRef[] {
  return credentialNames.map((name) => {
    const match = credentials.find((credential) => credential.name === name);
    if (!match) {
      return {
        name,
        visibility: "private",
        owner_username: null,
      };
    }
    return {
      name,
      visibility: match.visibility,
      owner_username:
        match.visibility === "global" ? null : (match.owner_username ?? null),
    };
  });
}

/**
 * Build embedded template payloads for every resolved template_id.
 * Missing templates are omitted (stale canvas refs).
 */
export function buildWorkflowExportTemplates(
  templateIds: number[],
  templates: Template[],
): WorkflowExportTemplate[] {
  const byId = new Map(templates.map((template) => [template.id, template]));
  const result: WorkflowExportTemplate[] = [];

  for (const id of templateIds) {
    const template = byId.get(id);
    if (!template) continue;
    result.push({
      id: template.id,
      ...templateToExportPayload(template),
    });
  }

  return result;
}
