import type {
  ConditionGroup,
  ConditionItem,
  ConditionTree,
} from "@/components/features/inventory/types/device-selector";

/** A tree loaded from a saved inventory can nest deeper than the assistant ever writes. */
const MAX_DESCRIBE_DEPTH = 12;

function describeItems(
  items: readonly (ConditionItem | ConditionGroup)[],
  depth: number,
  lines: string[],
): void {
  const indent = "  ".repeat(depth);
  for (const item of items) {
    if ("type" in item && item.type === "group") {
      if (depth >= MAX_DESCRIBE_DEPTH) {
        lines.push(`${indent}(deeper groups omitted)`);
        continue;
      }
      const negated = item.logic === "NOT" ? "NOT " : "";
      lines.push(`${indent}${negated}group, match ${item.internalLogic}:`);
      describeItems(item.items, depth + 1, lines);
    } else {
      const condition = item as ConditionItem;
      lines.push(
        `${indent}${condition.field} ${condition.operator.replaceAll("_", " ")} ${condition.value}`,
      );
    }
  }
}

/** One readable line per condition or group of an inventory filter, for a proposal card. */
export function describeConditionTree(tree: ConditionTree): string[] {
  const lines = [`Match ${tree.internalLogic} of:`];
  describeItems(tree.items, 1, lines);
  return lines;
}
