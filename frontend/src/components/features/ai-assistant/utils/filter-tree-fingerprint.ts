import type {
  ConditionGroup,
  ConditionItem,
  ConditionTree,
} from "@/components/features/inventory/types/device-selector";

type TreeItem = ConditionItem | ConditionGroup;

const MAX_FINGERPRINT_DEPTH = 12;

function shape(items: readonly TreeItem[], depth = 0): unknown[] {
  return items.map((item) =>
    "type" in item && item.type === "group"
      ? [
          item.logic,
          item.internalLogic,
          depth >= MAX_FINGERPRINT_DEPTH ? "…" : shape(item.items, depth + 1),
        ]
      : [(item as ConditionItem).field, (item as ConditionItem).operator, (item as ConditionItem).value],
  );
}

/**
 * A cheap fingerprint of an inventory filter's logic, field, operator and value (the random item
 * ids are ignored). Used only to tell the user "the builder changed since this proposal was made".
 */
export function filterTreeFingerprint(tree: ConditionTree): string {
  const parts = JSON.stringify([tree.internalLogic, shape(tree.items)]);
  let hash = 5381;
  for (let index = 0; index < parts.length; index += 1) {
    hash = ((hash << 5) + hash + parts.charCodeAt(index)) | 0;
  }
  return `${parts.length}:${hash >>> 0}`;
}
