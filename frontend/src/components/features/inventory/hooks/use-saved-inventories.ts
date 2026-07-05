import { useCallback, useState } from "react";

import { useApi } from "@/hooks/use-api";
import {
  useCreateInventoryMutation,
  useUpdateInventoryMutation,
  useDeleteInventoryMutation,
} from "@/hooks/queries/use-saved-inventory-mutations";
import { useInventoryExportMutation } from "@/hooks/queries/use-inventory-export-mutation";
import { useInventoryImportMutation } from "@/hooks/queries/use-inventory-import-mutation";
import { useSavedInventoriesQuery } from "@/hooks/queries/use-saved-inventories-query";

import type { ConditionTree, LogicalCondition } from "../types/device-selector";
import { generateId } from "./use-condition-tree";
import { conditionTreeToSavedConditions, savedTreeToConditionTree } from "../utils/tree-format-converters";

export interface LoadedInventoryData {
  tree: ConditionTree;
  id: number;
  name: string;
  description?: string;
  scope: string;
  group_path?: string | null;
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

  const loadSavedInventories = useCallback(async () => {
    await reloadInventories();
  }, [reloadInventories]);

  const flatConditionsToTree = (flatConditions: LogicalCondition[]): ConditionTree => {
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
  };

  const saveInventory = async (
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
        await updateMutation.mutateAsync({
          id: existingId,
          description: description || null,
          conditions,
          group_path: group_path ?? null,
        });
      } else {
        await createMutation.mutateAsync({
          name,
          description: description || null,
          conditions,
          scope,
          group_path: group_path ?? null,
        });
      }

      return true;
    } finally {
      setIsSavingInventory(false);
    }
  };

  const loadInventory = async (inventoryId: number): Promise<LoadedInventoryData | null> => {
    const response = await apiCall<{
      id: number;
      name: string;
      description?: string;
      scope: string;
      group_path?: string | null;
      conditions: unknown[];
    }>(`sources/nautobot/${inventoryId}`);

    if (!response) {
      return null;
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
      tree,
      id: response.id,
      name: response.name,
      description: response.description,
      scope: response.scope,
      group_path: response.group_path ?? null,
    };
  };

  const updateInventoryDetails = async (
    inventoryId: number,
    name: string,
    description: string,
    scope: string,
    group_path?: string | null,
  ) => {
    await updateMutation.mutateAsync({
      id: inventoryId,
      name,
      description: description || null,
      scope,
      group_path: group_path ?? null,
    });
  };

  const deleteInventory = async (inventoryId: number) => {
    await deleteMutation.mutateAsync(inventoryId);
  };

  const exportInventory = async (inventoryId: number) => {
    await exportMutation.mutateAsync(inventoryId);
  };

  const importInventory = async (file: File) => {
    await importMutation.mutateAsync(file);
    await reloadInventories();
  };

  return {
    savedInventories,
    isLoadingInventories,
    isSavingInventory,
    loadSavedInventories,
    saveInventory,
    loadInventory,
    updateInventoryDetails,
    deleteInventory,
    exportInventory,
    importInventory,
  };
}
