import { treeToOperations } from "../condition-builder/tree-to-operation";
import { emptyTree, type FilterTree } from "../condition-builder/types";
import type { SavedInventory } from "../types/saved-inventory";

/**
 * Config a step stores when a saved inventory is selected.
 *
 * The step *links* to the inventory (`inventory_id`, plus its name for display):
 * at run time the backend resolves the saved inventory by id, so editing the
 * inventory changes what the next run targets. The filter / device list is
 * deliberately not copied into the step — a copy would be a second, silently
 * stale definition. Merging this patch also wipes any copy left by older versions.
 */
export function inventoryLinkPatch(inventory: SavedInventory): {
  inventory_id: number;
  inventory_name: string;
  inventory_type: "filter" | "static";
  device_filter: FilterTree;
  device_ids: string[];
} {
  return {
    inventory_id: inventory.id,
    inventory_name: inventory.name,
    inventory_type: inventory.inventory_type === "static" ? "static" : "filter",
    device_filter: emptyTree(),
    device_ids: [],
  };
}

export interface PreviewSelection {
  source_id: string;
  /** Saved inventory the step is linked to, if any. */
  inventory_id: number | null;
  inventory_type: "filter" | "static";
  /** Ad-hoc selection, used only when no saved inventory is linked. */
  device_filter: FilterTree;
  device_ids: string[];
}

export type PreviewRequest =
  | { method: "GET"; path: string }
  | { method: "POST"; path: string; body: Record<string, unknown> };

/**
 * The backend call that previews a step's devices — the same resolution a run
 * performs: a linked saved inventory by id, otherwise the step's own selection.
 */
export function previewRequestFor(selection: PreviewSelection): PreviewRequest {
  if (selection.inventory_id !== null) {
    return {
      method: "GET",
      path: `sources/nautobot/${selection.inventory_id}/devices?source_id=${encodeURIComponent(
        selection.source_id,
      )}`,
    };
  }
  if (selection.inventory_type === "static") {
    return {
      method: "POST",
      path: "sources/nautobot/preview-device-ids",
      body: { source_id: selection.source_id, device_ids: selection.device_ids },
    };
  }
  return {
    method: "POST",
    path: "sources/nautobot/preview",
    body: {
      source_id: selection.source_id,
      operations: treeToOperations(selection.device_filter),
    },
  };
}
