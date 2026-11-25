import { emptyTree, type FilterTree } from "./types";
import type { SavedConditionPayload } from "../types/saved-inventory";
import {
  conditionTreeToFilterTree,
  savedTreeToConditionTree,
} from "@/components/features/inventory/utils/tree-format-converters";

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
    const conditionTree = savedTreeToConditionTree((first as SavedConditionPayload).tree);
    if (conditionTree) {
      return conditionTreeToFilterTree(conditionTree);
    }
  }

  return emptyTree();
}
