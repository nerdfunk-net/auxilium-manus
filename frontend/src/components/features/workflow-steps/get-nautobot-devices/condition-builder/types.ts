export interface FilterCondition {
  id: string;
  field: string;
  operator: string;
  value: string;
}

export interface FilterGroup {
  id: string;
  logic: "AND" | "OR";
  negate: boolean;
  items: FilterItem[];
}

export type FilterItem = FilterCondition | FilterGroup;

export type FilterTree = FilterGroup;

export function isGroup(item: FilterItem): item is FilterGroup {
  return "items" in item;
}

export function isCondition(item: FilterItem): item is FilterCondition {
  return !("items" in item);
}

export function emptyTree(): FilterTree {
  return { id: "root", logic: "AND", negate: false, items: [] };
}

export function countConditions(tree: FilterTree): number {
  let count = 0;
  for (const item of tree.items) {
    if (isCondition(item)) {
      count += 1;
    } else {
      count += countConditions(item);
    }
  }
  return count;
}
