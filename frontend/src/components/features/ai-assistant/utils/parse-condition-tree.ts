import type {
  ConditionGroup,
  ConditionItem,
  ConditionTree,
} from "@/components/features/inventory/types/device-selector";

/** Deepest nesting the assistant produces: the root, then one level of groups. */
export const MAX_PROPOSED_TREE_ITEMS = 100;

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function parseCondition(value: unknown): ConditionItem | null {
  if (typeof value !== "object" || value === null) return null;
  const { id, field, operator, value: text } = value as Record<string, unknown>;
  if (!isText(id) || !isText(field) || !isText(operator) || !isText(text)) return null;
  return { id, field, operator, value: text };
}

function parseGroup(value: unknown): ConditionGroup | null {
  if (typeof value !== "object" || value === null) return null;
  const { id, type, logic, internalLogic, items } = value as Record<string, unknown>;
  if (!isText(id) || type !== "group" || !Array.isArray(items)) return null;
  if (logic !== "AND" && logic !== "NOT") return null;
  if (internalLogic !== "AND" && internalLogic !== "OR") return null;
  const parsed: ConditionItem[] = [];
  for (const item of items) {
    const condition = parseCondition(item);
    if (!condition) return null;
    parsed.push(condition);
  }
  return { id, type: "group", logic, internalLogic, items: parsed };
}

/**
 * Checks an inventory filter sent by the server before it is shown or put in the builder: the root,
 * its conditions and one level of groups, all well-formed. Returns a clean copy, or null.
 */
export function parseProposedConditionTree(value: unknown): ConditionTree | null {
  if (typeof value !== "object" || value === null) return null;
  const { type, internalLogic, items } = value as Record<string, unknown>;
  if (type !== "root" || !Array.isArray(items) || items.length > MAX_PROPOSED_TREE_ITEMS) {
    return null;
  }
  if (internalLogic !== "AND" && internalLogic !== "OR") return null;
  const parsed: (ConditionItem | ConditionGroup)[] = [];
  for (const item of items) {
    const entry =
      typeof item === "object" && item !== null && "type" in item
        ? parseGroup(item)
        : parseCondition(item);
    if (!entry) return null;
    parsed.push(entry);
  }
  return { type: "root", internalLogic, items: parsed };
}
