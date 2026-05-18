import type { LogicalConditionPayload, LogicalOperationPayload } from "@/hooks/queries/use-device-selection-preview-mutation";
import { isCondition, isGroup } from "./types";
import type { FilterTree, FilterGroup } from "./types";

function groupToOperation(group: FilterGroup): LogicalOperationPayload {
  const conditions: LogicalConditionPayload[] = group.items
    .filter(isCondition)
    .map(({ field, operator, value }) => ({ field, operator, value }));

  const nested: LogicalOperationPayload[] = group.items
    .filter(isGroup)
    .map((sub) => {
      const op = groupToOperation(sub);
      if (sub.negate) {
        return { operation_type: "NOT", conditions: [], nested_operations: [op] };
      }
      return op;
    });

  return {
    operation_type: group.logic,
    conditions,
    nested_operations: nested,
  };
}

export function treeToOperations(tree: FilterTree): LogicalOperationPayload[] {
  if (tree.items.length === 0) return [];
  const op = groupToOperation(tree);
  if (tree.negate) {
    return [{ operation_type: "NOT", conditions: [], nested_operations: [op] }];
  }
  return [op];
}
