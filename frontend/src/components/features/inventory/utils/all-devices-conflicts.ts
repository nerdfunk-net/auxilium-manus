import type { ConditionGroup, ConditionItem, ConditionTree } from "../types/device-selector";

import { ALL_DEVICES_FIELD } from "./field-operators";

/** Shown next to the builder; the backend refuses the same shape with the same meaning. */
export const ALL_DEVICES_OR_MESSAGE =
  "All Devices is combined with other conditions under OR. Every device OR anything is every " +
  "device, so the other conditions would do nothing. Switch that connector to AND, or put what " +
  "to leave out in a negated (NOT) group.";

type Item = ConditionItem | ConditionGroup;

const isGroup = (item: Item): item is ConditionGroup => "type" in item && item.type === "group";
const isNotGroup = (item: Item): boolean => isGroup(item) && item.logic === "NOT";
const isAllDevices = (item: Item): boolean => !isGroup(item) && item.field === ALL_DEVICES_FIELD;

/**
 * True when ``items`` are ORed and one of them is All Devices next to anything that is not a NOT
 * group. A NOT group beside it is subtracted, not ORed, so it stays valid. A single regular item
 * is never a conflict.
 */
function ordersAreDead(items: Item[]): boolean {
  const regular = items.filter((item) => !isNotGroup(item));
  return regular.length > 1 && regular.some(isAllDevices);
}

function groupConflicts(group: ConditionGroup): boolean {
  // A NOT group is evaluated as a NOT operation whatever its inner logic says.
  if (group.logic !== "NOT" && group.internalLogic === "OR" && ordersAreDead(group.items)) {
    return true;
  }
  return group.items.some((item) => isGroup(item) && groupConflicts(item));
}

/**
 * The reason the tree cannot be previewed or saved because of All Devices, or null. Mirrors the
 * backend rule on ``LogicalOperation`` (``all_devices`` under OR beside other conditions).
 */
export function findAllDevicesConflict(tree: ConditionTree): string | null {
  const conflict =
    (tree.internalLogic === "OR" && ordersAreDead(tree.items)) ||
    tree.items.some((item) => isGroup(item) && groupConflicts(item));
  return conflict ? ALL_DEVICES_OR_MESSAGE : null;
}
