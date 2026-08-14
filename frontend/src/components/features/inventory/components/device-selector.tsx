"use client";

import { useState, useEffect, useCallback } from "react";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

import { Button } from "@/components/ui/button";
import { UserPlus } from "lucide-react";

import { ConditionTreeBuilder } from "./condition-tree-builder";
import { DeviceTable } from "./device-table";
import { SelectedInventoryList } from "./selected-inventory-list";
import { HelpModal } from "../dialogs/help-modal";
import { LoadInventoryModal } from "../dialogs/load-inventory-modal";
import { LogicalTreeModal } from "../dialogs/logical-tree-modal";
import { ManageInventoryModal } from "../dialogs/manage-inventory-modal";
import { SaveDeviceListModal } from "../dialogs/save-device-list-modal";
import { SaveInventoryModal } from "../dialogs/save-inventory-modal";
import { useConditionTree } from "../hooks/use-condition-tree";
import { useDeviceFilter } from "../hooks/use-device-filter";
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

  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showSaveDeviceListModal, setShowSaveDeviceListModal] = useState(false);
  const [showLoadModal, setShowLoadModal] = useState(false);
  const [showManageModal, setShowManageModal] = useState(false);
  const [showLogicalTreeModal, setShowLogicalTreeModal] = useState(false);
  const [showHelpModal, setShowHelpModal] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);

  const [loadedInventory, setLoadedInventory] = useState<Pick<
    LoadedInventoryData,
    "id" | "name" | "description" | "scope" | "group_path" | "inventory_type"
  > | null>(null);

  useEffect(() => {
    if (initialConditions.length > 0) {
      setConditionTree(flatConditionsToTree(initialConditions));
    }
  }, [initialConditions, flatConditionsToTree, setConditionTree]);

  const handleOpenSaveModal = useCallback(async () => {
    if (conditionTree.items.length === 0) {
      toast({
        title: "Nothing to save",
        description: "Please add at least one condition before saving.",
        variant: "destructive",
      });
      return;
    }
    await saved.loadSavedInventories();
    setShowSaveModal(true);
  }, [conditionTree.items.length, saved, toast]);

  const handleOpenLoadModal = useCallback(async () => {
    await saved.loadSavedInventories();
    setShowLoadModal(true);
  }, [saved]);

  const handleOpenManageModal = useCallback(async () => {
    await saved.loadSavedInventories();
    setShowManageModal(true);
  }, [saved]);

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
          setSelectionMode(true);
        } else if (result.tree) {
          setConditionTree(result.tree);
          preview.setShowPreviewResults(false);
        }

        setShowLoadModal(false);
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

  const handleOpenSaveDeviceListModal = useCallback(async () => {
    if (selection.selectedCount === 0) {
      toast({
        title: "Nothing to save",
        description: "Add at least one device to the selection before saving.",
        variant: "destructive",
      });
      return;
    }
    await saved.loadSavedInventories();
    setShowSaveDeviceListModal(true);
  }, [selection.selectedCount, saved, toast]);

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
        onOpenLoadModal={handleOpenLoadModal}
        onOpenManageModal={handleOpenManageModal}
        onOpenSaveAsModal={handleOpenSaveModal}
        onPreview={preview.loadPreview}
        onSaveCurrent={handleDirectSave}
        onShowHelp={() => setShowHelpModal(true)}
        onShowLogicalTree={() => setShowLogicalTreeModal(true)}
        onToggleSelectionMode={() => setSelectionMode((v) => !v)}
        operatorOptions={deviceFilter.operatorOptions}
        removeItemFromTree={removeItemFromTree}
        selectedCustomField={deviceFilter.selectedCustomField}
        selectionMode={selectionMode}
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
        enableSelection={enableSelection || selectionMode}
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

      {selectionMode && preview.selectedIds.size > 0 ? (
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

      {selectionMode ? (
        <SelectedInventoryList
          devices={selection.selectedDevices}
          isSaving={saved.isSavingInventory}
          onRemoveDevice={selection.removeDevice}
          onRemoveSelected={selection.removeSelectedDevices}
          onSave={handleOpenSaveDeviceListModal}
          onSelectAllForRemoval={selection.selectAllForRemoval}
          onToggleRemovalSelect={selection.toggleRemovalSelect}
          removalSelectedIds={selection.removalSelectedIds}
        />
      ) : null}

      <SaveInventoryModal
        currentConditionTree={conditionTree}
        initialDescription={loadedInventory?.description}
        initialGroupPath={loadedInventory?.group_path}
        initialName={loadedInventory?.name}
        isOpen={showSaveModal}
        isSaving={saved.isSavingInventory}
        onClose={() => setShowSaveModal(false)}
        onSave={handleSaveInventory}
        savedInventories={saved.savedInventories}
      />

      <SaveDeviceListModal
        devices={selection.selectedDevices}
        initialDescription={
          loadedInventory?.inventory_type === "static" ? loadedInventory.description : undefined
        }
        initialGroupPath={
          loadedInventory?.inventory_type === "static" ? loadedInventory.group_path : undefined
        }
        initialName={
          loadedInventory?.inventory_type === "static" ? loadedInventory.name : undefined
        }
        isOpen={showSaveDeviceListModal}
        isSaving={saved.isSavingInventory}
        onClose={() => setShowSaveDeviceListModal(false)}
        onSave={handleSaveDeviceList}
        savedInventories={saved.savedInventories}
      />

      <LoadInventoryModal
        isLoading={saved.isLoadingInventories}
        isOpen={showLoadModal}
        onClose={() => setShowLoadModal(false)}
        onLoad={handleLoadInventory}
        savedInventories={saved.savedInventories}
      />

      <ManageInventoryModal
        isLoading={saved.isLoadingInventories}
        isOpen={showManageModal}
        onClose={() => setShowManageModal(false)}
        onDelete={saved.deleteInventory}
        onExport={handleExportInventory}
        onImport={handleImportInventory}
        onUpdate={saved.updateInventoryDetails}
        savedInventories={saved.savedInventories}
      />

      <LogicalTreeModal
        conditionTree={conditionTree}
        isOpen={showLogicalTreeModal}
        onClose={() => setShowLogicalTreeModal(false)}
      />

      <HelpModal isOpen={showHelpModal} onClose={() => setShowHelpModal(false)} />
    </div>
  );
}
