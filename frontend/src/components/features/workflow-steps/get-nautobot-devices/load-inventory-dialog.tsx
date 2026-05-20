"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, FileText, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useGetNautobotDevicesFieldOptionsQuery } from "@/hooks/queries/use-get-nautobot-devices-field-options-query";
import {
  useInventoryGroupsQuery,
  useSavedInventoriesQuery,
} from "@/hooks/queries/use-saved-inventories-query";
import { cn } from "@/lib/utils";

import { formatLogicalExpression } from "./condition-builder/format-logical-expression";
import { savedConditionsToFilterTree } from "./condition-builder/saved-conditions";
import { InventoryGroupSidebar } from "./inventory-group-sidebar";
import type { SavedInventory } from "./types/saved-inventory";
import { ROOT_GROUP_ID } from "./types/saved-inventory";
import { inventoriesForGroup } from "./utils/inventory-groups";

interface LoadInventoryDialogProps {
  open: boolean;
  onClose: () => void;
  onLoad: (inventory: SavedInventory) => void;
}

export function LoadInventoryDialog({ open, onClose, onLoad }: LoadInventoryDialogProps) {
  const { data: inventories = [], isLoading } = useSavedInventoriesQuery({ enabled: open });
  const { data: groupPaths = [] } = useInventoryGroupsQuery({ enabled: open });
  const { data: fieldOptions } = useGetNautobotDevicesFieldOptionsQuery();
  const [selectedGroupId, setSelectedGroupId] = useState(ROOT_GROUP_ID);
  const [selectedInventory, setSelectedInventory] = useState<SavedInventory | null>(null);
  const [showTree, setShowTree] = useState(false);

  const selectedGroupPath =
    selectedGroupId === ROOT_GROUP_ID ? null : selectedGroupId;

  const groupInventories = useMemo(
    () => inventoriesForGroup(inventories, selectedGroupPath),
    [inventories, selectedGroupPath],
  );

  const expressionPreview = useMemo(() => {
    if (!selectedInventory) return "";
    const tree = savedConditionsToFilterTree(selectedInventory.conditions);
    return formatLogicalExpression(
      tree,
      fieldOptions?.fields ?? [],
      fieldOptions?.operators ?? [],
    );
  }, [selectedInventory, fieldOptions]);

  const resetDialog = () => {
    setSelectedGroupId(ROOT_GROUP_ID);
    setSelectedInventory(null);
    setShowTree(false);
  };

  const handleLoad = () => {
    if (!selectedInventory) return;
    onLoad(selectedInventory);
    onClose();
  };

  const groupListTitle = selectedGroupPath
    ? selectedGroupPath.split("/").pop()?.toUpperCase()
    : "ROOT";

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (isOpen) resetDialog();
        else onClose();
      }}
    >
      <DialogContent className="flex h-[min(85vh,720px)] max-w-4xl flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl">
        <DialogHeader className="shrink-0 border-b px-6 py-4">
          <DialogTitle>Load Saved Inventory</DialogTitle>
          <DialogDescription>
            Select a saved filter to replace the current device filter conditions.
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1">
          <InventoryGroupSidebar
            className="w-52 shrink-0"
            groupPaths={groupPaths}
            inventories={inventories}
            selectedGroupId={selectedGroupId}
            onSelectGroup={(node) => {
              setSelectedGroupId(node.id);
              setSelectedInventory(null);
            }}
            showNewGroupButton={false}
          />

          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="border-b border-slate-200 px-4 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Inventories in {groupListTitle}
              </p>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              {isLoading ? (
                <div className="flex items-center justify-center py-8 text-xs text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Loading…
                </div>
              ) : groupInventories.length === 0 ? (
                <p className="px-2 py-6 text-center text-xs text-muted-foreground">
                  No saved filters in this group.
                </p>
              ) : (
                <ul className="space-y-1">
                  {groupInventories.map((inv) => {
                    const isSelected = selectedInventory?.id === inv.id;
                    return (
                      <li key={inv.id}>
                        <button
                          className={cn(
                            "flex w-full items-center gap-2 rounded-md border px-2 py-2 text-left transition-colors",
                            isSelected
                              ? "border-teal-300 bg-teal-50"
                              : "border-transparent hover:bg-muted/50",
                          )}
                          type="button"
                          onClick={() => setSelectedInventory(inv)}
                          onDoubleClick={() => {
                            setSelectedInventory(inv);
                            onLoad(inv);
                            onClose();
                          }}
                        >
                          <FileText className="h-4 w-4 shrink-0 text-teal-500" aria-hidden />
                          <span className="min-w-0 flex-1 truncate text-sm font-medium">
                            {inv.name}
                          </span>
                          <Badge className="shrink-0 text-[10px]" variant="secondary">
                            {inv.scope}
                          </Badge>
                          <span className="shrink-0 text-[10px] text-muted-foreground">
                            {inv.created_by}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        </div>

        <div className="shrink-0 border-t bg-slate-50/50 px-6 py-4">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            General
          </p>
          {selectedInventory ? (
            <div className="space-y-2 text-sm">
              <div>
                <p className="font-medium">{selectedInventory.name}</p>
                {selectedInventory.description ? (
                  <p className="text-xs text-muted-foreground">
                    {selectedInventory.description}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <Badge variant="outline">{selectedInventory.scope}</Badge>
                <span>by {selectedInventory.created_by}</span>
                {selectedInventory.group_path ? (
                  <span>in {selectedInventory.group_path}</span>
                ) : (
                  <span>in Root</span>
                )}
              </div>
              <button
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                type="button"
                onClick={() => setShowTree((value) => !value)}
              >
                {showTree ? (
                  <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" aria-hidden />
                )}
                Show condition tree
              </button>
              {showTree ? (
                <pre className="max-h-32 overflow-auto rounded-md border bg-white p-3 text-[11px] text-muted-foreground">
                  {expressionPreview || "(empty)"}
                </pre>
              ) : null}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Select an inventory to see its details
            </p>
          )}
        </div>

        <DialogFooter className="shrink-0 border-t px-6 py-3">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" disabled={!selectedInventory} onClick={handleLoad}>
            Load
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
