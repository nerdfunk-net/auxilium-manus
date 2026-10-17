import type {
  FilterCondition,
  FilterGroup,
  FilterItem,
  FilterTree,
} from "@/components/features/workflow-steps/get-nautobot-devices/condition-builder/types";
import {
  isCondition,
} from "@/components/features/workflow-steps/get-nautobot-devices/condition-builder/types";

import type { ConditionGroup, ConditionItem, ConditionTree } from "../types/device-selector";
import { generateId } from "../hooks/use-condition-tree";

function isConditionTree(value: unknown): value is ConditionTree {
  return (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    (value as ConditionTree).type === "root"
  );
}

function isFilterTree(value: unknown): value is FilterTree {
  return (
    typeof value === "object" &&
    value !== null &&
    "items" in value &&
    Array.isArray((value as FilterTree).items) &&
    !("type" in value && (value as ConditionTree).type === "root")
  );
}

function convertFilterItems(items: FilterItem[]): (ConditionItem | ConditionGroup)[] {
  return items.map((item) => {
    if (isCondition(item)) {
      return {
        id: item.id,
        field: item.field,
        operator: item.operator,
        value: item.value,
      };
    }
    const converted = convertFilterGroup(item, false);
    if ("type" in converted && converted.type === "root") {
      if (converted.items.length === 1 && "type" in converted.items[0]! && converted.items[0]!.type === "group") {
        return converted.items[0] as ConditionGroup;
      }
      return {
        id: item.id,
        type: "group",
        logic: "AND",
        internalLogic: converted.internalLogic,
        items: converted.items,
      };
    }
    return converted as ConditionGroup;
  });
}

function convertFilterGroup(group: FilterGroup, isRoot: boolean): ConditionGroup | ConditionTree {
  const items = convertFilterItems(group.items);

  if (isRoot) {
    if (group.negate) {
      return {
        type: "root",
        internalLogic: "AND",
        items: [
          {
            id: group.id || generateId(),
            type: "group",
            logic: "NOT",
            internalLogic: group.logic,
            items,
          },
        ],
      };
    }

    return {
      type: "root",
      internalLogic: group.logic,
      items,
    };
  }

  return {
    id: group.id,
    type: "group",
    logic: group.negate ? "NOT" : "AND",
    internalLogic: group.logic,
    items,
  };
}

export function filterTreeToConditionTree(tree: FilterTree): ConditionTree {
  const converted = convertFilterGroup(tree, true);
  if (isConditionTree(converted)) {
    return converted;
  }
  return {
    type: "root",
    internalLogic: "AND",
    items: [converted],
  };
}

function convertConditionItems(
  items: (ConditionItem | ConditionGroup)[],
): FilterItem[] {
  return items.map((item) => {
    if ("type" in item && item.type === "group") {
      return convertConditionGroup(item);
    }
    const cond = item as ConditionItem;
    return {
      id: cond.id,
      field: cond.field,
      operator: cond.operator,
      value: cond.value,
    } satisfies FilterCondition;
  });
}

function convertConditionGroup(group: ConditionGroup): FilterGroup {
  return {
    id: group.id,
    logic: group.internalLogic,
    negate: group.logic === "NOT",
    items: convertConditionItems(group.items),
  };
}

export function conditionTreeToFilterTree(tree: ConditionTree): FilterTree {
  const rootGroup: FilterGroup = {
    id: "root",
    logic: tree.internalLogic,
    negate: false,
    items: convertConditionItems(tree.items),
  };

  if (
    tree.items.length === 1 &&
    "type" in tree.items[0]! &&
    tree.items[0]!.type === "group" &&
    (tree.items[0] as ConditionGroup).logic === "NOT"
  ) {
    const notGroup = tree.items[0] as ConditionGroup;
    return {
      id: "root",
      logic: notGroup.internalLogic,
      negate: true,
      items: convertConditionItems(notGroup.items),
    };
  }

  return rootGroup;
}

export function savedTreeToConditionTree(tree: unknown): ConditionTree | null {
  if (!tree || typeof tree !== "object") {
    return null;
  }

  if (isConditionTree(tree)) {
    return tree;
  }

  if (isFilterTree(tree)) {
    return filterTreeToConditionTree(tree);
  }

  return null;
}

export function conditionTreeToSavedConditions(tree: ConditionTree) {
  return [{ version: 2, tree }];
}
