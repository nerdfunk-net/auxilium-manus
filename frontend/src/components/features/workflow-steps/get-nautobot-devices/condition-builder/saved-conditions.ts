import { emptyTree, type FilterTree } from "./types";
import type { SavedConditionPayload } from "../types/saved-inventory";

export function filterTreeToSavedConditions(tree: FilterTree): SavedConditionPayload[] {
  return [{ version: 2, tree }];
}

export function savedConditionsToFilterTree(
  conditions: SavedConditionPayload[] | unknown,
): FilterTree {
  if (!Array.isArray(conditions) || conditions.length === 0) {
    return emptyTree();
  }

  const first = conditions[0];
  if (
    first &&
    typeof first === "object" &&
    "version" in first &&
    (first as SavedConditionPayload).version === 2 &&
    "tree" in first &&
    (first as SavedConditionPayload).tree
  ) {
    const tree = (first as SavedConditionPayload).tree as FilterTree;
    if (tree && typeof tree === "object" && Array.isArray(tree.items)) {
      return tree;
    }
  }

  return emptyTree();
}
