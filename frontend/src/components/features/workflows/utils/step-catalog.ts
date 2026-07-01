import type { LucideIcon } from "lucide-react";

import type { Capability } from "@/lib/capability-types";

import type { PluginDefinition } from "../types/plugin-registry";
import type { StepPayload, WorkflowOutcomeField } from "../types/workflow-canvas";
import {
  ARTIFACT_TYPE_ORDER,
  formatPaletteCategory,
  resolveStepIcon,
} from "./step-visuals";

export interface PaletteItem extends StepPayload {
  icon: LucideIcon;
  paletteCategory: string;
}

export interface PaletteGroup {
  categoryKey: string;
  label: string;
  items: PaletteItem[];
}

function resolvePaletteCategory(plugin: PluginDefinition): string {
  return plugin.palette_category?.trim() || plugin.artifact_type;
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
  const paletteCategory = resolvePaletteCategory(plugin);
  return {
    ...toStepPayload(plugin),
    paletteCategory,
    icon: resolveStepIcon(plugin.id, paletteCategory),
  };
}

export function groupPaletteItems(plugins: PluginDefinition[]): PaletteGroup[] {
  const groups = new Map<string, PaletteItem[]>();

  for (const plugin of plugins) {
    const categoryKey = resolvePaletteCategory(plugin);
    const items = groups.get(categoryKey) ?? [];
    items.push(toPaletteItem(plugin));
    groups.set(categoryKey, items);
  }

  return Array.from(groups.entries())
    .sort(([left], [right]) => {
      const leftIndex = ARTIFACT_TYPE_ORDER.indexOf(left);
      const rightIndex = ARTIFACT_TYPE_ORDER.indexOf(right);
      const leftOrder = leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex;
      const rightOrder = rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex;
      return leftOrder - rightOrder || left.localeCompare(right);
    })
    .map(([categoryKey, items]) => ({
      categoryKey,
      label: formatPaletteCategory(categoryKey),
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
