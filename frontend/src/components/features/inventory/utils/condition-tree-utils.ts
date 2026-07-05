import type { ConditionGroup, ConditionItem, ConditionTree } from "../types/device-selector";

function formatOperator(operator: string): string {
  const operatorMap: Record<string, string> = {
    equals: "=",
    not_equals: "!=",
    contains: "contains",
    not_contains: "not contains",
    within_include: "within include",
    within: "within",
    exact: "exact",
  };
  return operatorMap[operator] ?? operator;
}

export function conditionTreeToExpression(
  tree: ConditionTree | ConditionGroup | null | undefined,
): string {
  if (!tree || !tree.items || tree.items.length === 0) {
    return "No conditions";
  }

  const items = tree.items;
  const logic = tree.internalLogic || "AND";

  const parts = items.map((item, index) => {
    if ("type" in item && item.type === "group") {
      const groupExpr = conditionTreeToExpression(item as ConditionGroup);
      const prefix = index > 0 ? ` ${item.logic} ` : "";
      return `${prefix}(${groupExpr})`;
    }

    const cond = item as ConditionItem;
    const operator = formatOperator(cond.operator);
    return `${cond.field} ${operator} "${cond.value}"`;
  });

  if (items.length === 1) {
    return parts[0] ?? "";
  }

  return parts
    .map((part, index) => {
      if (index === 0) return part;
      if (
        part.trim().startsWith("AND ") ||
        part.trim().startsWith("OR ") ||
        part.trim().startsWith("NOT ")
      ) {
        return part;
      }
      return `${logic} ${part}`;
    })
    .join(" ");
}
