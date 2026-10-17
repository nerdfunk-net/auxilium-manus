import { useCallback, useMemo, useState } from "react";

import { useApi } from "@/hooks/use-api";
import {
  useCreateInventoryMutation,
  useUpdateInventoryMutation,
  useDeleteInventoryMutation,
} from "@/hooks/queries/use-saved-inventory-mutations";
import { useInventoryExportMutation } from "@/hooks/queries/use-inventory-export-mutation";
import { useInventoryImportMutation } from "@/hooks/queries/use-inventory-import-mutation";
import { useSavedInventoriesQuery } from "@/hooks/queries/use-saved-inventories-query";

import type {
  ConditionTree,
  InventoryType,
  LogicalCondition,
} from "../types/device-selector";
import { generateId } from "./use-condition-tree";
import { conditionTreeToSavedConditions, savedTreeToConditionTree } from "../utils/tree-format-converters";

export interface LoadedInventoryData {
  inventory_type: InventoryType;
  tree?: ConditionTree;
  device_ids?: string[];
  id: number;
  name: string;
  description?: string;
  scope: string;
  group_path?: string | null;
}

// Module-level and pure, so it never needs to be a hook dependency.
function flatConditionsToTree(flatConditions: LogicalCondition[]): ConditionTree {
  const tree: ConditionTree = {
    type: "root",
    internalLogic: "AND",
    items: [],
  };

  flatConditions.forEach((condition) => {
    tree.items.push({
      id: generateId(),
      field: condition.field,
      operator: condition.operator,
      value: condition.value,
    });
  });

  return tree;
}

export function useSavedInventories() {
  const [isSavingInventory, setIsSavingInventory] = useState(false);
  const { apiCall } = useApi();

  const {
    data: savedInventories = [],
    isLoading: isLoadingInventories,
    refetch: reloadInventories,
  } = useSavedInventoriesQuery();

  const createMutation = useCreateInventoryMutation();
  const updateMutation = useUpdateInventoryMutation();
  const deleteMutation = useDeleteInventoryMutation();
  const exportMutation = useInventoryExportMutation();
  const importMutation = useInventoryImportMutation();

  const { mutateAsync: createInventory } = createMutation;
  const { mutateAsync: updateInventory } = updateMutation;
  const { mutateAsync: deleteInventoryMutation } = deleteMutation;
  const { mutateAsync: exportInventoryMutation } = exportMutation;
  const { mutateAsync: importInventoryMutation } = importMutation;

  const loadSavedInventories = useCallback(async () => {
    await reloadInventories();
  }, [reloadInventories]);

  const saveInventory = useCallback(
    async (
      name: string,
      description: string,
      scope: string,
      conditionTree: ConditionTree,
      isUpdate: boolean = false,
      existingId?: number,
      group_path?: string | null,
    ) => {
      setIsSavingInventory(true);
      try {
        const conditions = conditionTreeToSavedConditions(conditionTree);

        if (isUpdate && existingId) {
          await updateInventory({
            id: existingId,
            description: description || null,
            conditions,
            inventory_type: "filter",
            group_path: group_path ?? null,
          });
        } else {
          await createInventory({
            name,
            description: description || null,
            conditions,
            inventory_type: "filter",
            scope,
            group_path: group_path ?? null,
          });
        }

        return true;
      } finally {
        setIsSavingInventory(false);
      }
    },
    [createInventory, updateInventory],
  );

  const saveDeviceList = useCallback(
    async (
      name: string,
      description: string,
      scope: string,
      deviceIds: string[],
      isUpdate: boolean = false,
      existingId?: number,
      group_path?: string | null,
    ) => {
      setIsSavingInventory(true);
      try {
        if (isUpdate && existingId) {
          await updateInventory({
            id: existingId,
            description: description || null,
            inventory_type: "static",
            device_ids: deviceIds,
            group_path: group_path ?? null,
          });
        } else {
          await createInventory({
            name,
            description: description || null,
            inventory_type: "static",
            device_ids: deviceIds,
            conditions: [],
            scope,
            group_path: group_path ?? null,
          });
        }

        return true;
      } finally {
        setIsSavingInventory(false);
      }
    },
    [createInventory, updateInventory],
  );

  const loadInventory = useCallback(
    async (inventoryId: number): Promise<LoadedInventoryData | null> => {
      const response = await apiCall<{
        id: number;
        name: string;
        description?: string;
        scope: string;
        group_path?: string | null;
        conditions: unknown[];
        inventory_type?: InventoryType;
        device_ids?: string[];
      }>(`sources/nautobot/${inventoryId}`);

      if (!response) {
        return null;
      }

      if (response.inventory_type === "static") {
        return {
          inventory_type: "static",
          device_ids: response.device_ids ?? [],
          id: response.id,
          name: response.name,
          description: response.description,
          scope: response.scope,
          group_path: response.group_path ?? null,
        };
      }

      let tree: ConditionTree | null = null;
      if (response.conditions && response.conditions.length > 0) {
        const firstItem = response.conditions[0];

        if (
          firstItem &&
          typeof firstItem === "object" &&
          "version" in firstItem &&
          (firstItem as { version: number }).version === 2 &&
          "tree" in firstItem
        ) {
          tree = savedTreeToConditionTree((firstItem as { tree: unknown }).tree);
        } else {
          tree = flatConditionsToTree(response.conditions as LogicalCondition[]);
        }
      }

      if (!tree) {
        return null;
      }

      return {
        inventory_type: "filter",
        tree,
        id: response.id,
        name: response.name,
        description: response.description,
        scope: response.scope,
        group_path: response.group_path ?? null,
      };
    },
    [apiCall],
  );

  const updateInventoryDetails = useCallback(
    async (
      inventoryId: number,
      name: string,
      description: string,
      scope: string,
      group_path?: string | null,
    ) => {
      await updateInventory({
        id: inventoryId,
        name,
        description: description || null,
        scope,
        group_path: group_path ?? null,
      });
    },
    [updateInventory],
  );

  const deleteInventory = useCallback(
    async (inventoryId: number) => {
      await deleteInventoryMutation(inventoryId);
    },
    [deleteInventoryMutation],
  );

  const exportInventory = useCallback(
    async (inventoryId: number) => {
      await exportInventoryMutation(inventoryId);
    },
    [exportInventoryMutation],
  );

  const importInventory = useCallback(
    async (file: File) => {
      await importInventoryMutation(file);
      await reloadInventories();
    },
    [importInventoryMutation, reloadInventories],
  );

  return useMemo(
    () => ({
      savedInventories,
      isLoadingInventories,
      isSavingInventory,
      loadSavedInventories,
      saveInventory,
      saveDeviceList,
      loadInventory,
      updateInventoryDetails,
      deleteInventory,
      exportInventory,
      importInventory,
    }),
    [
      savedInventories,
      isLoadingInventories,
      isSavingInventory,
      loadSavedInventories,
      saveInventory,
      saveDeviceList,
      loadInventory,
      updateInventoryDetails,
      deleteInventory,
      exportInventory,
      importInventory,
    ],
  );
}
