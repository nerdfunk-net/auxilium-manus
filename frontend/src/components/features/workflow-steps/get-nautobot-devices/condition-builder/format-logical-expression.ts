import type { FieldOption } from "@/hooks/queries/use-get-nautobot-devices-field-options-query";

import { isCondition, isGroup } from "./types";
import type { FilterCondition, FilterGroup, FilterItem, FilterTree } from "./types";

function labelFor(
  value: string,
  options: FieldOption[] | undefined,
  fallback = value,
): string {
  return options?.find((o) => o.value === value)?.label ?? (fallback || "—");
}

function formatCondition(
  condition: FilterCondition,
  fields: FieldOption[],
  operators: FieldOption[],
): string {
  const field = labelFor(condition.field, fields, condition.field || "…");
  const operator = labelFor(condition.operator, operators, condition.operator);
  const value = condition.value || "…";
  return `${field} ${operator} ${value}`;
}

function formatGroup(
  group: FilterGroup,
  fields: FieldOption[],
  operators: FieldOption[],
): string {
  if (group.items.length === 0) return "";

  const parts = group.items
    .map((item) => formatItem(item, fields, operators))
    .filter(Boolean);

  if (parts.length === 0) return "";

  const joined = parts.join(` ${group.logic} `);
  const expression = parts.length > 1 ? `(${joined})` : joined;
  return group.negate ? `NOT ${expression}` : expression;
}

function formatItem(
  item: FilterItem,
  fields: FieldOption[],
  operators: FieldOption[],
): string {
  if (isCondition(item)) {
    return formatCondition(item, fields, operators);
  }
  if (isGroup(item)) {
    return formatGroup(item, fields, operators);
  }
  return "";
}

export function formatLogicalExpression(
  tree: FilterTree,
  fields: FieldOption[] = [],
  operators: FieldOption[] = [],
): string {
  return formatGroup(tree, fields, operators);
}
