"use client";

import { HelpModal } from "../dialogs/help-modal";
import { LoadInventoryModal } from "../dialogs/load-inventory-modal";
import { LogicalTreeModal } from "../dialogs/logical-tree-modal";
import { ManageInventoryModal } from "../dialogs/manage-inventory-modal";
import { SaveDeviceListModal } from "../dialogs/save-device-list-modal";
import { SaveInventoryModal } from "../dialogs/save-inventory-modal";
import type { useDeviceSelectorModals } from "../hooks/use-device-selector-modals";
import type { LoadedInventoryData } from "../hooks/use-saved-inventories";
import type { useSavedInventories } from "../hooks/use-saved-inventories";
import type { useSelectedInventory } from "../hooks/use-selected-inventory";
import type { ConditionTree } from "../types/device-selector";

interface DeviceSelectorModalsProps {
  modals: ReturnType<typeof useDeviceSelectorModals>;
  conditionTree: ConditionTree;
  saved: ReturnType<typeof useSavedInventories>;
  selection: ReturnType<typeof useSelectedInventory>;
  loadedInventory: Pick<
    LoadedInventoryData,
    "id" | "name" | "description" | "scope" | "group_path" | "inventory_type"
  > | null;
  onSaveInventory: (
    name: string,
    description: string,
    scope: string,
    isUpdate: boolean,
    existingId?: number,
    group_path?: string | null,
  ) => Promise<boolean>;
  onSaveDeviceList: (
    name: string,
    description: string,
    scope: string,
    isUpdate: boolean,
    existingId?: number,
    group_path?: string | null,
  ) => Promise<boolean>;
  onLoadInventory: (id: number) => Promise<void>;
  onExportInventory: (id: number) => Promise<void>;
  onImportInventory: (file: File) => Promise<void>;
}

export function DeviceSelectorModals({
  modals,
  conditionTree,
  saved,
  selection,
  loadedInventory,
  onSaveInventory,
  onSaveDeviceList,
  onLoadInventory,
  onExportInventory,
  onImportInventory,
}: DeviceSelectorModalsProps) {
  return (
    <>
      <SaveInventoryModal
        currentConditionTree={conditionTree}
        initialDescription={loadedInventory?.description}
        initialGroupPath={loadedInventory?.group_path}
        initialName={loadedInventory?.name}
        isOpen={modals.showSaveModal}
        isSaving={saved.isSavingInventory}
        onClose={modals.closeSaveModal}
        onSave={onSaveInventory}
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
        isOpen={modals.showSaveDeviceListModal}
        isSaving={saved.isSavingInventory}
        onClose={modals.closeSaveDeviceListModal}
        onSave={onSaveDeviceList}
        savedInventories={saved.savedInventories}
      />

      <LoadInventoryModal
        isLoading={saved.isLoadingInventories}
        isOpen={modals.showLoadModal}
        onClose={modals.closeLoadModal}
        onLoad={onLoadInventory}
        savedInventories={saved.savedInventories}
      />

      <ManageInventoryModal
        isLoading={saved.isLoadingInventories}
        isOpen={modals.showManageModal}
        onClose={modals.closeManageModal}
        onDelete={saved.deleteInventory}
        onExport={onExportInventory}
        onImport={onImportInventory}
        onUpdate={saved.updateInventoryDetails}
        savedInventories={saved.savedInventories}
      />

      <LogicalTreeModal
        conditionTree={conditionTree}
        isOpen={modals.showLogicalTreeModal}
        onClose={modals.closeLogicalTreeModal}
      />

      <HelpModal isOpen={modals.showHelpModal} onClose={modals.closeHelpModal} />
    </>
  );
}
