"use client";

import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { savedConditionsToFilterTree } from "./condition-builder/saved-conditions";
import type { FilterTree } from "./condition-builder/types";
import { DeviceFilterCard } from "./device-filter-card";
import { LoadInventoryDialog } from "./load-inventory-dialog";
import { SaveInventoryDialog } from "./save-inventory-dialog";
import type { SavedInventory } from "./types/saved-inventory";

interface InventoryBuilderDialogProps {
  open: boolean;
  onClose: () => void;
  nautobot_url: string;
  nautobot_token: string;
  initialTree: FilterTree;
  onApply: (tree: FilterTree) => void;
}

export function InventoryBuilderDialog({
  open,
  onClose,
  nautobot_url,
  nautobot_token,
  initialTree,
  onApply,
}: InventoryBuilderDialogProps) {
  const [tree, setTree] = useState<FilterTree>(initialTree);
  const [loadedInventory, setLoadedInventory] = useState<SavedInventory | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveAsNew, setSaveAsNew] = useState(false);
  const [loadOpen, setLoadOpen] = useState(false);

  const handleOpen = useCallback(() => {
    setTree(initialTree);
    setLoadedInventory(null);
  }, [initialTree]);

  const handleApply = useCallback(() => {
    onApply(tree);
    onClose();
  }, [tree, onApply, onClose]);

  const handleSaveClick = useCallback(() => {
    if (loadedInventory) {
      setSaveAsNew(false);
      setSaveOpen(true);
    } else {
      setSaveAsNew(true);
      setSaveOpen(true);
    }
  }, [loadedInventory]);

  const handleSaveAsClick = useCallback(() => {
    setSaveAsNew(true);
    setSaveOpen(true);
  }, []);

  const handleLoadInventory = useCallback((inventory: SavedInventory) => {
    setTree(savedConditionsToFilterTree(inventory.conditions));
    setLoadedInventory(inventory);
  }, []);

  const handleSaveClose = useCallback(() => {
    setSaveOpen(false);
  }, []);

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(isOpen) => {
          if (isOpen) handleOpen();
          else onClose();
        }}
      >
        <DialogContent className="flex h-[85vh] max-w-4xl flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl">
          <DialogHeader className="sr-only">
            <DialogTitle>Device Filter</DialogTitle>
            <DialogDescription>
              Build filter conditions to select devices from the inventory.
            </DialogDescription>
          </DialogHeader>

          <div className="flex min-h-0 flex-1 flex-col">
            <DeviceFilterCard
              className="h-full rounded-none border-0 shadow-none"
              loadedInventory={loadedInventory}
              nautobot_token={nautobot_token}
              nautobot_url={nautobot_url}
              onChange={setTree}
              onLoad={() => setLoadOpen(true)}
              onSave={handleSaveClick}
              onSaveAs={handleSaveAsClick}
              tree={tree}
            />
          </div>

          <DialogFooter className="shrink-0 border-t bg-white px-4 py-3">
            <Button onClick={onClose} size="sm" type="button" variant="outline">
              Cancel
            </Button>
            <Button onClick={handleApply} size="sm" type="button">
              Apply
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SaveInventoryDialog
        open={saveOpen}
        tree={tree}
        existingInventory={loadedInventory}
        saveAsNew={saveAsNew}
        onClose={handleSaveClose}
        onSaved={(inventory) => {
          if (!saveAsNew) {
            setLoadedInventory(inventory);
          }
        }}
      />

      <LoadInventoryDialog
        open={loadOpen}
        onLoad={handleLoadInventory}
        onClose={() => setLoadOpen(false)}
      />
    </>
  );
}
