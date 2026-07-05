import { useCallback, useState } from "react";

import type {
  ConditionGroup,
  ConditionItem,
  ConditionTree,
  LogicalCondition,
} from "../types/device-selector";

export const generateId = () =>
  `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;

export const createEmptyTree = (): ConditionTree => ({
  type: "root",
  internalLogic: "AND",
  items: [],
});

const EMPTY_TREE = createEmptyTree();

export function useConditionTree() {
  const [conditionTree, setConditionTree] = useState<ConditionTree>(EMPTY_TREE);
  const [currentGroupPath, setCurrentGroupPath] = useState<string[]>([]);

  const flatConditionsToTree = useCallback(
    (flatConditions: LogicalCondition[]): ConditionTree => {
      if (!flatConditions || flatConditions.length === 0) {
        return createEmptyTree();
      }

      const tree = createEmptyTree();
      tree.items = flatConditions.map((c) => ({
        id: generateId(),
        field: c.field,
        operator: c.operator,
        value: c.value,
      }));

      if (flatConditions.length > 0 && flatConditions[0]?.logic) {
        tree.internalLogic = flatConditions[0].logic as "AND" | "OR";
      }

      return tree;
    },
    [],
  );

  const addConditionToTree = useCallback(
    (field: string, operator: string, value: string) => {
      const newCondition: ConditionItem = {
        id: generateId(),
        field,
        operator,
        value,
      };

      setConditionTree((prevTree) => {
        const newTree = { ...prevTree };

        if (currentGroupPath.length === 0) {
          newTree.items = [...newTree.items, newCondition];
        } else {
          const findAndAddToGroup = (
            items: (ConditionItem | ConditionGroup)[],
            pathIndex: number,
          ): (ConditionItem | ConditionGroup)[] =>
            items.map((item) => {
              if (
                "type" in item &&
                item.type === "group" &&
                item.id === currentGroupPath[pathIndex]
              ) {
                if (pathIndex === currentGroupPath.length - 1) {
                  return {
                    ...item,
                    items: [...item.items, newCondition],
                  };
                }
                return {
                  ...item,
                  items: findAndAddToGroup(item.items, pathIndex + 1),
                };
              }
              return item;
            });

          newTree.items = findAndAddToGroup(newTree.items, 0);
        }

        return newTree;
      });
    },
    [currentGroupPath],
  );

  const addGroup = useCallback(
    (logic: "AND" | "OR", negate: boolean) => {
      let groupLogic: "AND" | "OR" | "NOT" = logic;
      if (negate) {
        groupLogic = "NOT";
      }

      const newGroup: ConditionGroup = {
        id: generateId(),
        type: "group",
        logic: groupLogic,
        internalLogic: "AND",
        items: [],
      };

      setConditionTree((prevTree) => {
        const newTree = { ...prevTree };

        if (currentGroupPath.length === 0) {
          newTree.items = [...newTree.items, newGroup];
        } else {
          const findAndAddToGroup = (
            items: (ConditionItem | ConditionGroup)[],
            pathIndex: number,
          ): (ConditionItem | ConditionGroup)[] =>
            items.map((item) => {
              if (
                "type" in item &&
                item.type === "group" &&
                item.id === currentGroupPath[pathIndex]
              ) {
                if (pathIndex === currentGroupPath.length - 1) {
                  return {
                    ...item,
                    items: [...item.items, newGroup],
                  };
                }
                return {
                  ...item,
                  items: findAndAddToGroup(item.items, pathIndex + 1),
                };
              }
              return item;
            });

          newTree.items = findAndAddToGroup(newTree.items, 0);
        }

        return newTree;
      });
    },
    [currentGroupPath],
  );

  const removeItemFromTree = useCallback((itemId: string) => {
    setConditionTree((prevTree) => {
      const removeFromItems = (
        items: (ConditionItem | ConditionGroup)[],
      ): (ConditionItem | ConditionGroup)[] =>
        items
          .filter((item) => item.id !== itemId)
          .map((item) => {
            if ("type" in item && item.type === "group") {
              return {
                ...item,
                items: removeFromItems(item.items),
              };
            }
            return item;
          });

      return {
        ...prevTree,
        items: removeFromItems(prevTree.items),
      };
    });
  }, []);

  const updateGroupLogic = useCallback((groupId: string, newLogic: "AND" | "OR") => {
    setConditionTree((prevTree) => {
      const updateLogic = (
        items: (ConditionItem | ConditionGroup)[],
      ): (ConditionItem | ConditionGroup)[] =>
        items.map((item) => {
          if ("type" in item && item.type === "group") {
            if (item.id === groupId) {
              return {
                ...item,
                internalLogic: newLogic,
              };
            }
            return {
              ...item,
              items: updateLogic(item.items),
            };
          }
          return item;
        });

      return {
        ...prevTree,
        items: updateLogic(prevTree.items),
      };
    });
  }, []);

  const findGroupPath = useCallback(
    (groupId: string): string[] | null => {
      const findRecursive = (
        items: (ConditionItem | ConditionGroup)[],
        currentPath: string[],
      ): string[] | null => {
        for (const item of items) {
          if ("type" in item && item.type === "group") {
            if (item.id === groupId) {
              return [...currentPath, item.id];
            }
            const pathInGroup = findRecursive(item.items, [...currentPath, item.id]);
            if (pathInGroup) {
              return pathInGroup;
            }
          }
        }
        return null;
      };

      return findRecursive(conditionTree.items, []);
    },
    [conditionTree],
  );

  return {
    conditionTree,
    setConditionTree,
    currentGroupPath,
    setCurrentGroupPath,
    addConditionToTree,
    addGroup,
    removeItemFromTree,
    updateGroupLogic,
    findGroupPath,
    flatConditionsToTree,
  };
}
