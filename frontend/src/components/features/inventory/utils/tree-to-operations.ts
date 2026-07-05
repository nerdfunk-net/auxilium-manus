import type {
  BackendCondition,
  BackendOperation,
  ConditionGroup,
  ConditionItem,
  ConditionTree,
} from "../types/device-selector";

function convertItem(item: ConditionItem | ConditionGroup): BackendOperation {
  if ("type" in item && item.type === "group") {
    const group = item as ConditionGroup;
    const groupConditions: BackendCondition[] = [];
    const nestedOps: BackendOperation[] = [];

    group.items.forEach((subItem) => {
      if ("type" in subItem && subItem.type === "group") {
        const convertedSubGroup = convertItem(subItem);
        if (subItem.logic === "NOT") {
          convertedSubGroup.operation_type = "NOT";
        }
        nestedOps.push(convertedSubGroup);
      } else {
        const cond = subItem as ConditionItem;
        groupConditions.push({
          field: cond.field,
          operator: cond.operator,
          value: cond.value,
        });
      }
    });

    return {
      operation_type: group.internalLogic,
      conditions: groupConditions,
      nested_operations: nestedOps,
      _parentLogic: group.logic,
    };
  }

  const cond = item as ConditionItem;
  return {
    operation_type: "AND",
    conditions: [
      {
        field: cond.field,
        operator: cond.operator,
        value: cond.value,
      },
    ],
    nested_operations: [],
  };
}

export function buildOperationsFromTree(
  tree: ConditionTree | ConditionGroup,
): BackendOperation[] {
  const items = tree.items;
  if (items.length === 0) return [];

  const internalLogic = "internalLogic" in tree ? tree.internalLogic : "AND";
  const regularItems: BackendOperation[] = [];
  const notItems: BackendOperation[] = [];

  items.forEach((item) => {
    const converted = convertItem(item);
    if ("type" in item && item.type === "group" && item.logic === "NOT") {
      converted.operation_type = "NOT";
      notItems.push(converted);
    } else {
      regularItems.push(converted);
    }
  });

  const operations: BackendOperation[] = [];

  if (regularItems.length > 0) {
    if (regularItems.length === 1) {
      const firstItem = regularItems[0];
      if (firstItem) {
        operations.push(firstItem);
      }
    } else {
      const rootConditions: BackendCondition[] = [];
      const nestedOps: BackendOperation[] = [];

      regularItems.forEach((item) => {
        if (item.conditions.length > 1 || item.nested_operations.length > 0) {
          nestedOps.push(item);
        } else if (item.conditions.length === 1) {
          rootConditions.push(...item.conditions);
        }
      });

      operations.push({
        operation_type: internalLogic,
        conditions: rootConditions,
        nested_operations: nestedOps,
      });
    }
  }

  operations.push(...notItems);
  return operations;
}
