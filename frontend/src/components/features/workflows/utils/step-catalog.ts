import type { LucideIcon } from "lucide-react";

import type { Capability } from "@/lib/capability-types";

import type { PluginDefinition } from "../types/plugin-registry";
import type { StepPayload, WorkflowOutcomeField } from "../types/workflow-canvas";
import { ARTIFACT_TYPE_ORDER, formatArtifactType, resolveStepIcon } from "./step-visuals";

export interface PaletteItem extends StepPayload {
  icon: LucideIcon;
}

export interface PaletteGroup {
  artifactType: string;
  label: string;
  items: PaletteItem[];
}

export function toStepPayload(plugin: PluginDefinition): StepPayload {
  return {
    kind: plugin.id,
    title: plugin.name,
    description: plugin.description,
    artifactType: plugin.artifact_type,
    requires: (plugin.requires ?? []) as Capability[],
    requiresParsed: plugin.requires_parsed ?? [],
    produces: (plugin.produces ?? []) as Capability[],
    producesParsed: plugin.produces_parsed ?? [],
    consumes: (plugin.consumes ?? []) as Capability[],
    outcomes: plugin.outcomes.map((outcome): WorkflowOutcomeField => ({ name: outcome.name })),
  };
}

function toPaletteItem(plugin: PluginDefinition): PaletteItem {
  return {
    ...toStepPayload(plugin),
    icon: resolveStepIcon(plugin.id, plugin.artifact_type),
  };
}

export function groupPaletteItems(plugins: PluginDefinition[]): PaletteGroup[] {
  const groups = new Map<string, PaletteItem[]>();

  for (const plugin of plugins) {
    const items = groups.get(plugin.artifact_type) ?? [];
    items.push(toPaletteItem(plugin));
    groups.set(plugin.artifact_type, items);
  }

  return Array.from(groups.entries())
    .sort(([left], [right]) => {
      const leftIndex = ARTIFACT_TYPE_ORDER.indexOf(left);
      const rightIndex = ARTIFACT_TYPE_ORDER.indexOf(right);
      const leftOrder = leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex;
      const rightOrder = rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex;
      return leftOrder - rightOrder || left.localeCompare(right);
    })
    .map(([artifactType, items]) => ({
      artifactType,
      label: formatArtifactType(artifactType),
      items: items.sort((left, right) => left.title.localeCompare(right.title)),
    }));
}

export function findPluginByKind(
  plugins: PluginDefinition[],
  kind: string,
): PluginDefinition | undefined {
  return plugins.find((plugin) => plugin.id === kind);
}

/** dataTransfer MIME type used for HTML5 drag-and-drop of a catalog step onto the canvas. */
export const STEP_DRAG_MIME_TYPE = "application/x-am-step";
