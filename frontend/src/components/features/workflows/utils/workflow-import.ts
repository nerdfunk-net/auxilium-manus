import type { Credential } from "@/components/features/settings/credentials/types";
import type {
  Template,
  TemplateListItem,
} from "@/components/features/templates/types";
import { parseTemplateExportPayload } from "@/components/features/templates/utils/template-import";
import { templateExportToCreatePayload } from "@/components/features/templates/utils/template-export";

import type { StaticAttributeDef } from "../types/workflow-persistence";
import {
  WORKFLOW_EXPORT_FORMAT,
  type WorkflowExportCredentialRef,
  type WorkflowExportFile,
  type WorkflowExportTemplate,
} from "../types/workflow-export";
import {
  collectCredentialReferencesFromCanvas,
  collectGitRepositoryIdsFromCanvas,
  collectSourceIdsFromCanvas,
} from "./workflow-export";

export class WorkflowImportParseError extends Error {}

/** Step `kind` -> the Credential.type a step's credential_reference resolves
 * against (see backend/workflow_steps/common/credential_resolver.py and the
 * per-step executors that call it). Unlisted kinds default to "ssh", which
 * matches every step in this table today except the two exceptions below. */
const SHARED_SECRET_STEP_KINDS = new Set(["encrypt-attribute", "decrypt-attribute"]);
const GENERIC_STEP_KINDS = new Set(["add-pyats-testbed"]);

export type RequiredCredentialType = "ssh" | "generic" | "shared_secret";

export interface CredentialRemapRequirement {
  name: string;
  visibility: WorkflowExportCredentialRef["visibility"] | "unknown";
  owner_username: string | null;
  credentialType: RequiredCredentialType;
}

export interface GitRepositoryRemapRequirement {
  id: number;
}

export interface SourceRemapRequirement {
  sourceId: string;
}

export type SourceRemapType = "nautobot" | "mattermost" | "batfish" | "pyats";

export const SOURCE_CONFIG_KEY_BY_TYPE: Record<SourceRemapType, string> = {
  nautobot: "nautobot_source_id",
  mattermost: "mattermost_source_id",
  batfish: "batfish_source_id",
  pyats: "pyats_source_id",
};

/**
 * Determine which Credential.type a given credential_reference name must
 * resolve to, based on the kind(s) of step(s) that reference it on the
 * canvas. Falls back to "ssh" when the name isn't used by a step kind with a
 * different resolver, preserving today's default behaviour.
 */
function inferCredentialType(
  canvasNodes: Record<string, unknown>[],
  name: string,
): RequiredCredentialType {
  for (const node of canvasNodes) {
    const data = node.data;
    if (typeof data !== "object" || data === null) continue;
    const dataRecord = data as Record<string, unknown>;
    const pluginConfig = dataRecord.pluginConfig;
    if (typeof pluginConfig !== "object" || pluginConfig === null) continue;
    const ref = (pluginConfig as Record<string, unknown>).credential_reference;
    if (typeof ref !== "string" || ref.trim() !== name) continue;

    const kind = dataRecord.kind;
    if (typeof kind !== "string") continue;
    if (SHARED_SECRET_STEP_KINDS.has(kind)) return "shared_secret";
    if (GENERIC_STEP_KINDS.has(kind)) return "generic";
  }
  return "ssh";
}

const REQUIRED_ARRAY_FIELDS = [
  "canvas_nodes",
  "canvas_edges",
  "canvas_groups",
] as const;

function parseCredentialReferences(
  raw: unknown,
): WorkflowExportCredentialRef[] {
  if (!Array.isArray(raw)) return [];

  const refs: WorkflowExportCredentialRef[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null) continue;
    const record = item as Record<string, unknown>;
    if (typeof record.name !== "string" || !record.name.trim()) continue;
    const visibility = record.visibility === "global" ? "global" : "private";
    const owner_username =
      typeof record.owner_username === "string" ? record.owner_username : null;
    refs.push({
      name: record.name.trim(),
      visibility,
      owner_username: visibility === "global" ? null : owner_username,
    });
  }
  return refs;
}

function parseWorkflowTemplates(raw: unknown): WorkflowExportTemplate[] {
  if (!Array.isArray(raw)) return [];

  const templates: WorkflowExportTemplate[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null) continue;
    const record = item as Record<string, unknown>;
    const id =
      typeof record.id === "number"
        ? record.id
        : Number(record.id);
    if (!Number.isInteger(id) || id <= 0) continue;
    try {
      const payload = parseTemplateExportPayload(record);
      templates.push({ id, ...payload });
    } catch {
      // Skip malformed template entries
    }
  }
  return templates;
}

export function parseWorkflowExportFile(raw: unknown): WorkflowExportFile {
  if (typeof raw !== "object" || raw === null) {
    throw new WorkflowImportParseError(
      "File does not contain a valid JSON object.",
    );
  }

  const obj = raw as Record<string, unknown>;

  if (obj.export_format !== WORKFLOW_EXPORT_FORMAT) {
    throw new WorkflowImportParseError(
      "Unrecognized workflow export file. Expected a file exported from this application.",
    );
  }
  if (typeof obj.name !== "string" || obj.name.trim().length === 0) {
    throw new WorkflowImportParseError(
      "Import file is missing a workflow name.",
    );
  }
  for (const field of REQUIRED_ARRAY_FIELDS) {
    if (!Array.isArray(obj[field])) {
      throw new WorkflowImportParseError(
        `Import file is missing or has an invalid "${field}" array.`,
      );
    }
  }

  return {
    export_format: WORKFLOW_EXPORT_FORMAT,
    exported_at:
      typeof obj.exported_at === "string"
        ? obj.exported_at
        : new Date().toISOString(),
    name: obj.name,
    description: typeof obj.description === "string" ? obj.description : null,
    folder: typeof obj.folder === "string" ? obj.folder : null,
    visibility: obj.visibility === "public" ? "public" : "private",
    // Legacy export files predate wiki notes — default to none.
    notes: typeof obj.notes === "string" ? obj.notes : null,
    canvas_nodes: obj.canvas_nodes as Record<string, unknown>[],
    canvas_edges: obj.canvas_edges as Record<string, unknown>[],
    canvas_groups: obj.canvas_groups as Record<string, unknown>[],
    // Legacy export files predate static_attributes — default to none rather
    // than rejecting the whole import.
    static_attributes: Array.isArray(obj.static_attributes)
      ? (obj.static_attributes as StaticAttributeDef[])
      : [],
    credential_references: parseCredentialReferences(obj.credential_references),
    templates: parseWorkflowTemplates(obj.templates),
  };
}

function credentialNeedsRemap(
  name: string,
  meta: WorkflowExportCredentialRef | undefined,
  visibleCredentials: Credential[],
  currentUsername: string,
): boolean {
  const hasVisibleName = visibleCredentials.some(
    (credential) => credential.name === name,
  );
  const hasOwnPrivate = visibleCredentials.some(
    (credential) =>
      credential.name === name && credential.visibility === "private",
  );

  // Legacy files without sidecar metadata: keep when the name is visible.
  if (!meta) {
    return !hasVisibleName;
  }

  if (meta.visibility === "global") {
    return !hasVisibleName;
  }

  // Private: always remap when owner is missing or belongs to another user.
  if (
    meta.owner_username == null ||
    meta.owner_username !== currentUsername
  ) {
    return true;
  }

  // Same-user private: keep only when that private credential still exists.
  return !hasOwnPrivate;
}

/**
 * Decide which exported credential names must be remapped before import save.
 */
export function buildCredentialRemapRequirements(
  exportMeta: WorkflowExportCredentialRef[],
  canvasNodes: Record<string, unknown>[],
  visibleCredentials: Credential[],
  currentUsername: string,
): CredentialRemapRequirement[] {
  const metaByName = new Map(
    exportMeta.map((ref) => [ref.name, ref] as const),
  );
  const canvasNames = collectCredentialReferencesFromCanvas(canvasNodes);
  const requirements: CredentialRemapRequirement[] = [];

  for (const name of canvasNames) {
    const meta = metaByName.get(name);
    if (
      !credentialNeedsRemap(
        name,
        meta,
        visibleCredentials,
        currentUsername,
      )
    ) {
      continue;
    }
    requirements.push({
      name,
      visibility: meta?.visibility ?? "unknown",
      owner_username: meta?.owner_username ?? null,
      credentialType: inferCredentialType(canvasNodes, name),
    });
  }

  return requirements;
}

/**
 * Decide which canvas-referenced git_repository_id values must be remapped:
 * any id not present among the target environment's active git repositories.
 */
export function buildGitRepositoryRemapRequirements(
  canvasNodes: Record<string, unknown>[],
  availableRepositoryIds: number[],
): GitRepositoryRemapRequirement[] {
  const available = new Set(availableRepositoryIds);
  return collectGitRepositoryIdsFromCanvas(canvasNodes)
    .filter((id) => !available.has(id))
    .map((id) => ({ id }));
}

/**
 * Decide which canvas-referenced source ids (nautobot/mattermost/batfish/
 * pyats `*_source_id`) must be remapped: any id not present among the
 * target environment's configured sources of that type.
 */
export function buildSourceRemapRequirements(
  canvasNodes: Record<string, unknown>[],
  configKey: string,
  availableSourceIds: string[],
): SourceRemapRequirement[] {
  const available = new Set(availableSourceIds);
  return collectSourceIdsFromCanvas(canvasNodes, configKey)
    .filter((sourceId) => !available.has(sourceId))
    .map((sourceId) => ({ sourceId }));
}

/**
 * Return a deep-copied canvas with a flat string pluginConfig field
 * rewritten according to remap (old value → new value). Entries mapping to
 * the same value are no-ops; empty target clears the field. Used for
 * credential_reference and every `*_source_id` field.
 */
export function applyStringFieldRemap(
  canvasNodes: Record<string, unknown>[],
  configKey: string,
  remap: ReadonlyMap<string, string>,
): Record<string, unknown>[] {
  if (remap.size === 0) {
    return canvasNodes.map((node) => structuredClone(node));
  }

  return canvasNodes.map((node) => {
    const cloned = structuredClone(node) as Record<string, unknown>;
    const data = cloned.data;
    if (typeof data !== "object" || data === null) return cloned;

    const dataRecord = data as Record<string, unknown>;
    const pluginConfig = dataRecord.pluginConfig;
    if (typeof pluginConfig !== "object" || pluginConfig === null) {
      return cloned;
    }

    const config = pluginConfig as Record<string, unknown>;
    const ref = config[configKey];
    if (typeof ref !== "string") return cloned;

    const trimmed = ref.trim();
    if (!remap.has(trimmed)) return cloned;

    config[configKey] = remap.get(trimmed) ?? "";
    return cloned;
  });
}

/**
 * Rewrite a flat numeric pluginConfig field (oldId → newId map). Used for
 * template_id and git_repository_id.
 */
export function applyNumericFieldRemap(
  canvasNodes: Record<string, unknown>[],
  configKey: string,
  remap: ReadonlyMap<number, number>,
): Record<string, unknown>[] {
  if (remap.size === 0) {
    return canvasNodes.map((node) => structuredClone(node));
  }

  return canvasNodes.map((node) => {
    const cloned = structuredClone(node) as Record<string, unknown>;
    const data = cloned.data;
    if (typeof data !== "object" || data === null) return cloned;

    const dataRecord = data as Record<string, unknown>;
    const pluginConfig = dataRecord.pluginConfig;
    if (typeof pluginConfig !== "object" || pluginConfig === null) {
      return cloned;
    }

    const config = pluginConfig as Record<string, unknown>;
    const raw = config[configKey];
    if (raw === null || raw === undefined || raw === "") return cloned;
    const oldId = typeof raw === "number" ? raw : Number(raw);
    if (!Number.isInteger(oldId) || !remap.has(oldId)) return cloned;

    config[configKey] = remap.get(oldId) ?? null;
    return cloned;
  });
}

export interface ResolveWorkflowTemplatesOptions {
  exportedTemplates: WorkflowExportTemplate[];
  existingTemplates: TemplateListItem[];
  createTemplate: (
    payload: ReturnType<typeof templateExportToCreatePayload>,
  ) => Promise<Template>;
}

/**
 * Match exported templates by name. Reuse existing IDs when the name exists;
 * otherwise create the template. Returns a map of export id → local id.
 */
export async function resolveWorkflowTemplatesOnImport({
  exportedTemplates,
  existingTemplates,
  createTemplate,
}: ResolveWorkflowTemplatesOptions): Promise<Map<number, number>> {
  const existingByName = new Map(
    existingTemplates.map((template) => [template.name, template.id] as const),
  );
  const idRemap = new Map<number, number>();

  for (const exported of exportedTemplates) {
    const existingId = existingByName.get(exported.name);
    if (existingId !== undefined) {
      idRemap.set(exported.id, existingId);
      continue;
    }

    const created = await createTemplate(
      templateExportToCreatePayload(exported),
    );
    existingByName.set(created.name, created.id);
    idRemap.set(exported.id, created.id);
  }

  return idRemap;
}

export { collectCredentialReferencesFromCanvas };
