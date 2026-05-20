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
import { useGetNautobotDevicesPreviewMutation } from "@/hooks/queries/use-get-nautobot-devices-preview-mutation";

import { DeviceFilterCard } from "./device-filter-card";
import type { FilterTree } from "./condition-builder/types";

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
  const previewMutation = useGetNautobotDevicesPreviewMutation();

  const handleOpen = useCallback(() => {
    setTree(initialTree);
    previewMutation.reset();
  }, [initialTree, previewMutation]);

  const handleApply = useCallback(() => {
    onApply(tree);
    onClose();
  }, [tree, onApply, onClose]);

  return (
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
            nautobot_token={nautobot_token}
            nautobot_url={nautobot_url}
            onChange={setTree}
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
  );
}
