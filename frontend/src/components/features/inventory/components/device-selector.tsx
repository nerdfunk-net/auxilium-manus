"use client";

import { useState, useEffect, useCallback } from "react";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

import { Button } from "@/components/ui/button";
import { UserPlus } from "lucide-react";

import { ConditionTreeBuilder } from "./condition-tree-builder";
import { DeviceSelectorModals } from "./device-selector-modals";
import { DeviceTable } from "./device-table";
import { SelectedInventoryList } from "./selected-inventory-list";
import { useConditionTree } from "../hooks/use-condition-tree";
import { useDeviceFilter } from "../hooks/use-device-filter";
import { useDeviceSelectorModals } from "../hooks/use-device-selector-modals";
import { mapPreviewDevices, useDevicePreview } from "../hooks/use-device-preview";
import type { LoadedInventoryData } from "../hooks/use-saved-inventories";
import { useSavedInventories } from "../hooks/use-saved-inventories";
import { useSelectedInventory } from "../hooks/use-selected-inventory";
import type {
  DeviceInfo,
  DeviceSelectorProps,
  InventoryPreviewApiResponse,
  LogicalCondition,
} from "../types/device-selector";

export type {
  DeviceSelectorProps,
  LogicalCondition,
  DeviceInfo,
  ConditionTree,
  ConditionItem,
  ConditionGroup,
} from "../types/device-selector";

const EMPTY_CONDITIONS: LogicalCondition[] = [];
const EMPTY_DEVICES: DeviceInfo[] = [];
const EMPTY_DEVICE_IDS: string[] = [];

export function DeviceSelector({
  sourceId,
  sourceReady,
  onDevicesSelected,
  showActions = true,
  showSaveLoad = true,
  initialConditions = EMPTY_CONDITIONS,
  initialDevices = EMPTY_DEVICES,
  enableSelection = false,
  selectedDeviceIds = EMPTY_DEVICE_IDS,
  onSelectionChange,
  onInventoryLoaded,
}: DeviceSelectorProps) {
  const { toast } = useToast();
  const { apiCall } = useApi();

  const {
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
  } = useConditionTree();

  const deviceFilter = useDeviceFilter({
    sourceId,
    sourceReady,
  });

  const previewOptions = { sourceId, sourceReady };

  const preview = useDevicePreview(
    conditionTree,
    previewOptions,
    initialDevices,
    selectedDeviceIds,
    onDevicesSelected,
    onSelectionChange,
  );

  const saved = useSavedInventories();
  const selection = useSelectedInventory();

  const modals = useDeviceSelectorModals({
    saved,
    conditionTreeItemCount: conditionTree.items.length,
    selectedDeviceCount: selection.selectedCount,
  });

  const [loadedInventory, setLoadedInventory] = useState<Pick<
    LoadedInventoryData,
    "id" | "name" | "description" | "scope" | "group_path" | "inventory_type"
  > | null>(null);

  useEffect(() => {
    if (initialConditions.length > 0) {
      setConditionTree(flatConditionsToTree(initialConditions));
    }
  }, [initialConditions, flatConditionsToTree, setConditionTree]);

  const handleSaveInventory = useCallback(
    async (
      name: string,
      description: string,
      scope: string,
      isUpdate: boolean,
      existingId?: number,
      group_path?: string | null,
    ) => {
      try {
        return await saved.saveInventory(
          name,
          description,
          scope,
          conditionTree,
          isUpdate,
          existingId,
          group_path,
        );
      } catch (error) {
        toast({
          title: "Save failed",
          description: (error as Error).message,
          variant: "destructive",
        });
        return false;
      }
    },
    [saved, conditionTree, toast],
  );

  const handleLoadInventory = useCallback(
    async (id: number) => {
      try {
        const result = await saved.loadInventory(id);
        if (!result) return;

        setLoadedInventory({
          id: result.id,
          name: result.name,
          description: result.description,
          scope: result.scope,
          group_path: result.group_path,
          inventory_type: result.inventory_type,
        });

        if (result.inventory_type === "static") {
          const params = new URLSearchParams({ source_id: sourceId });
          const response = await apiCall<InventoryPreviewApiResponse>(
            `sources/nautobot/${id}/devices?${params.toString()}`,
          );
          selection.replaceAll(mapPreviewDevices(response.devices));
          modals.setSelectionMode(true);
        } else if (result.tree) {
          setConditionTree(result.tree);
          preview.setShowPreviewResults(false);
        }

        modals.closeLoadModal();
        onInventoryLoaded?.(id);
      } catch (error) {
        toast({
          title: "Load failed",
          description: (error as Error).message,
          variant: "destructive",
        });
      }
    },
    [
      saved,
      setConditionTree,
      preview,
      selection,
      apiCall,
      sourceId,
      onInventoryLoaded,
      toast,
      modals,
    ],
  );

  const handleSaveDeviceList = useCallback(
    async (
      name: string,
      description: string,
      scope: string,
      isUpdate: boolean,
      existingId?: number,
      group_path?: string | null,
    ) => {
      try {
        return await saved.saveDeviceList(
          name,
          description,
          scope,
          selection.selectedDevices.map((device) => device.id),
          isUpdate,
          existingId,
          group_path,
        );
      } catch (error) {
        toast({
          title: "Save failed",
          description: (error as Error).message,
          variant: "destructive",
        });
        return false;
      }
    },
    [saved, selection.selectedDevices, toast],
  );

  const handleAddToSelection = useCallback(() => {
    const devicesToAdd = preview.previewDevices.filter((device) =>
      preview.selectedIds.has(device.id),
    );
    selection.addDevices(devicesToAdd);
    preview.setSelectedIds(new Set());
  }, [preview, selection]);

  const handleDirectSave = useCallback(async () => {
    if (!loadedInventory) return;
    try {
      await saved.saveInventory(
        loadedInventory.name,
        loadedInventory.description ?? "",
        loadedInventory.scope,
        conditionTree,
        true,
        loadedInventory.id,
        loadedInventory.group_path,
      );
    } catch (error) {
      toast({
        title: "Save failed",
        description: (error as Error).message,
        variant: "destructive",
      });
    }
  }, [loadedInventory, conditionTree, saved, toast]);

  const handleExportInventory = useCallback(
    async (id: number) => {
      try {
        await saved.exportInventory(id);
      } catch (error) {
        toast({
          title: "Export failed",
          description: (error as Error).message,
          variant: "destructive",
        });
      }
    },
    [saved, toast],
  );

  const handleImportInventory = useCallback(
    async (file: File) => {
      try {
        await saved.importInventory(file);
      } catch (error) {
        toast({
          title: "Import failed",
          description: (error as Error).message,
          variant: "destructive",
        });
      }
    },
    [saved, toast],
  );

  return (
    <div className="space-y-6">
      <ConditionTreeBuilder
        addConditionToTree={addConditionToTree}
        addGroup={addGroup}
        conditionTree={conditionTree}
        currentField={deviceFilter.currentField}
        currentGroupPath={currentGroupPath}
        currentLogic={deviceFilter.currentLogic}
        currentNegate={deviceFilter.currentNegate}
        currentOperator={deviceFilter.currentOperator}
        currentValue={deviceFilter.currentValue}
        customFields={deviceFilter.customFields}
        fieldOptions={deviceFilter.fieldOptions}
        fieldValues={deviceFilter.fieldValues}
        findGroupPath={findGroupPath}
        handleCustomFieldSelect={deviceFilter.handleCustomFieldSelect}
        handleFieldChange={deviceFilter.handleFieldChange}
        handleOperatorChange={deviceFilter.handleOperatorChange}
        isLoadingCustomFields={deviceFilter.isLoadingCustomFields}
        isLoadingFieldValues={deviceFilter.isLoadingFieldValues}
        isLoadingPreview={preview.isLoadingPreview}
        isSavingCurrent={saved.isSavingInventory}
        loadedInventoryName={loadedInventory?.name}
        onOpenLoadModal={modals.handleOpenLoadModal}
        onOpenManageModal={modals.handleOpenManageModal}
        onOpenSaveAsModal={modals.handleOpenSaveModal}
        onPreview={preview.loadPreview}
        onSaveCurrent={handleDirectSave}
        onShowHelp={modals.openHelpModal}
        onShowLogicalTree={modals.openLogicalTreeModal}
        onToggleSelectionMode={modals.toggleSelectionMode}
        operatorOptions={deviceFilter.operatorOptions}
        removeItemFromTree={removeItemFromTree}
        selectedCustomField={deviceFilter.selectedCustomField}
        selectionMode={modals.selectionMode}
        setConditionTree={setConditionTree}
        setCurrentField={deviceFilter.setCurrentField}
        setCurrentGroupPath={setCurrentGroupPath}
        setCurrentLogic={deviceFilter.setCurrentLogic}
        setCurrentNegate={deviceFilter.setCurrentNegate}
        setCurrentOperator={deviceFilter.setCurrentOperator}
        setCurrentValue={deviceFilter.setCurrentValue}
        showActions={showActions}
        showSaveLoad={showSaveLoad}
        sourceReady={sourceReady}
        updateGroupLogic={updateGroupLogic}
      />

      <DeviceTable
        currentPage={preview.currentPage}
        currentPageDevices={preview.currentPageDevices}
        devices={preview.previewDevices}
        enableSelection={enableSelection || modals.selectionMode}
        onClearSelection={() => preview.setSelectedIds(new Set())}
        onPageChange={preview.handlePageChange}
        onSelectAll={preview.handleSelectAll}
        onSelectDevice={preview.handleSelectDevice}
        operationsExecuted={preview.operationsExecuted}
        pageSize={preview.pageSize}
        selectedIds={preview.selectedIds}
        setPageSize={preview.setPageSize}
        showPreviewResults={preview.showPreviewResults}
        totalDevices={preview.totalDevices}
        totalPages={preview.totalPages}
      />

      {modals.selectionMode && preview.selectedIds.size > 0 ? (
        <div className="flex justify-end">
          <Button
            className="flex items-center space-x-2 border-0 bg-step-hover text-step-foreground hover:bg-step-hover/90"
            onClick={handleAddToSelection}
            type="button"
          >
            <UserPlus className="h-4 w-4" />
            <span>Add Devices to selection</span>
          </Button>
        </div>
      ) : null}

      {modals.selectionMode ? (
        <SelectedInventoryList
          devices={selection.selectedDevices}
          isSaving={saved.isSavingInventory}
          onRemoveDevice={selection.removeDevice}
          onRemoveSelected={selection.removeSelectedDevices}
          onSave={modals.handleOpenSaveDeviceListModal}
          onSelectAllForRemoval={selection.selectAllForRemoval}
          onToggleRemovalSelect={selection.toggleRemovalSelect}
          removalSelectedIds={selection.removalSelectedIds}
        />
      ) : null}

      <DeviceSelectorModals
        conditionTree={conditionTree}
        loadedInventory={loadedInventory}
        modals={modals}
        onExportInventory={handleExportInventory}
        onImportInventory={handleImportInventory}
        onLoadInventory={handleLoadInventory}
        onSaveDeviceList={handleSaveDeviceList}
        onSaveInventory={handleSaveInventory}
        saved={saved}
        selection={selection}
      />
    </div>
  );
}
