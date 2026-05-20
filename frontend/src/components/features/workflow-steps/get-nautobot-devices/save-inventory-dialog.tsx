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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGetNautobotDevicesFieldOptionsQuery } from "@/hooks/queries/use-get-nautobot-devices-field-options-query";
import {
  useCreateInventoryMutation,
  useUpdateInventoryMutation,
} from "@/hooks/queries/use-saved-inventory-mutations";
import {
  useInventoryGroupsQuery,
  useSavedInventoriesQuery,
} from "@/hooks/queries/use-saved-inventories-query";
import { cn } from "@/lib/utils";

import { filterTreeToSavedConditions } from "./condition-builder/saved-conditions";
import { formatLogicalExpression } from "./condition-builder/format-logical-expression";
import type { FilterTree } from "./condition-builder/types";
import { InventoryGroupSidebar } from "./inventory-group-sidebar";
import { NewGroupDialog } from "./new-group-dialog";
import type { SavedInventory } from "./types/saved-inventory";
import { ROOT_GROUP_ID } from "./types/saved-inventory";
import { childGroupPath, inventoriesForGroup } from "./utils/inventory-groups";

interface SaveInventoryDialogProps {
  open: boolean;
  onClose: () => void;
  tree: FilterTree;
  /** When set, Save updates this inventory instead of creating a new one. */
  existingInventory?: SavedInventory | null;
  saveAsNew?: boolean;
  onSaved?: (inventory: SavedInventory) => void;
}

export function SaveInventoryDialog({
  open,
  onClose,
  tree,
  existingInventory = null,
  saveAsNew = false,
  onSaved,
}: SaveInventoryDialogProps) {
  const { data: inventories = [], isLoading: inventoriesLoading } =
    useSavedInventoriesQuery({ enabled: open });
  const { data: groupPaths = [] } = useInventoryGroupsQuery({ enabled: open });
  const { data: fieldOptions } = useGetNautobotDevicesFieldOptionsQuery();
  const createMutation = useCreateInventoryMutation();
  const updateMutation = useUpdateInventoryMutation();

  const [selectedGroupId, setSelectedGroupId] = useState(ROOT_GROUP_ID);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState("global");
  const [showTree, setShowTree] = useState(false);
  const [newGroupOpen, setNewGroupOpen] = useState(false);
  const [localGroupPaths, setLocalGroupPaths] = useState<string[]>([]);

  const isUpdate = Boolean(existingInventory && !saveAsNew);
  const isSaving = createMutation.isPending || updateMutation.isPending;

  const mergedGroupPaths = useMemo(() => {
    const set = new Set([...groupPaths, ...localGroupPaths]);
    if (existingInventory?.group_path) set.add(existingInventory.group_path);
    return [...set];
  }, [groupPaths, localGroupPaths, existingInventory]);

  const selectedGroupPath =
    selectedGroupId === ROOT_GROUP_ID ? null : selectedGroupId;

  const groupInventories = useMemo(
    () => inventoriesForGroup(inventories, selectedGroupPath),
    [inventories, selectedGroupPath],
  );

  const expressionPreview = useMemo(
    () =>
      formatLogicalExpression(
        tree,
        fieldOptions?.fields ?? [],
        fieldOptions?.operators ?? [],
      ),
    [tree, fieldOptions],
  );

  const resetForm = () => {
    if (existingInventory && !saveAsNew) {
      setName(existingInventory.name);
      setDescription(existingInventory.description ?? "");
      setScope(existingInventory.scope);
      setSelectedGroupId(existingInventory.group_path ?? ROOT_GROUP_ID);
    } else if (existingInventory && saveAsNew) {
      setName(`${existingInventory.name} (copy)`);
      setDescription(existingInventory.description ?? "");
      setScope(existingInventory.scope);
      setSelectedGroupId(existingInventory.group_path ?? ROOT_GROUP_ID);
    } else {
      setName("");
      setDescription("");
      setScope("global");
      setSelectedGroupId(ROOT_GROUP_ID);
    }
    setShowTree(false);
  };

  const handleSave = async () => {
    if (!name.trim()) return;

    const payload = {
      name: name.trim(),
      description: description.trim() || null,
      scope,
      group_path: selectedGroupPath,
      conditions: filterTreeToSavedConditions(tree),
    };

    let saved: SavedInventory;
    if (isUpdate && existingInventory) {
      saved = await updateMutation.mutateAsync({ id: existingInventory.id, ...payload });
    } else {
      saved = await createMutation.mutateAsync(payload);
    }
    onSaved?.(saved);
    onClose();
  };

  const handleNewGroup = (groupName: string) => {
    const path = childGroupPath(selectedGroupPath, groupName);
    if (!path) return;
    setLocalGroupPaths((prev) => (prev.includes(path) ? prev : [...prev, path]));
    setSelectedGroupId(path);
  };

  const groupListTitle = selectedGroupPath
    ? selectedGroupPath.split("/").pop()?.toUpperCase()
    : "ROOT";

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(isOpen) => {
          if (isOpen) resetForm();
          else onClose();
        }}
      >
        <DialogContent className="flex h-[min(85vh,720px)] max-w-4xl flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl">
          <DialogHeader className="shrink-0 border-b px-6 py-4">
            <DialogTitle>
              {isUpdate ? "Save Inventory Filter" : "Save Inventory Filter"}
            </DialogTitle>
            <DialogDescription>
              Save the current logical expression to a group for reuse across workflows.
            </DialogDescription>
          </DialogHeader>

          <div className="flex min-h-0 flex-1">
            <InventoryGroupSidebar
              className="w-52 shrink-0"
              groupPaths={mergedGroupPaths}
              inventories={inventories}
              selectedGroupId={selectedGroupId}
              onSelectGroup={(node) => setSelectedGroupId(node.id)}
              onNewGroup={() => setNewGroupOpen(true)}
            />

            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              <div className="border-b border-slate-200 px-4 py-2">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Inventories in {groupListTitle}
                </p>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-2">
                {inventoriesLoading ? (
                  <div className="flex items-center justify-center py-8 text-xs text-muted-foreground">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Loading…
                  </div>
                ) : groupInventories.length === 0 ? (
                  <p className="px-2 py-6 text-center text-xs text-muted-foreground">
                    No saved filters in this group yet.
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {groupInventories.map((inv) => (
                      <li
                        key={inv.id}
                        className="flex items-center gap-2 rounded-md border border-transparent px-2 py-2 hover:bg-muted/50"
                      >
                        <FileText className="h-4 w-4 shrink-0 text-teal-500" aria-hidden />
                        <span className="min-w-0 flex-1 truncate text-sm">{inv.name}</span>
                        <Badge className="shrink-0 text-[10px]" variant="secondary">
                          {inv.scope}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>

          <div className="shrink-0 border-t bg-slate-50/50 px-6 py-4">
            <p className="mb-3 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              General
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="save-inv-name">
                  Name <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="save-inv-name"
                  placeholder="e.g., Windows Servers in Berlin"
                  value={name}
                  disabled={isSaving}
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="save-inv-scope">Scope</Label>
                <Select value={scope} disabled={isSaving} onValueChange={setScope}>
                  <SelectTrigger id="save-inv-scope" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="global">Global (all users)</SelectItem>
                    <SelectItem value="private">Private (only you)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="save-inv-description">Description</Label>
                <textarea
                  id="save-inv-description"
                  className={cn(
                    "border-input bg-background placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 min-h-[72px] w-full rounded-md border px-3 py-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] disabled:opacity-50",
                  )}
                  placeholder="Describe what this filter does…"
                  value={description}
                  disabled={isSaving}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </div>
            </div>
            <button
              className="mt-3 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
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
              <pre className="mt-2 max-h-32 overflow-auto rounded-md border bg-white p-3 text-[11px] text-muted-foreground">
                {expressionPreview || "(empty filter)"}
              </pre>
            ) : null}
          </div>

          <DialogFooter className="shrink-0 border-t px-6 py-3">
            <Button type="button" variant="outline" disabled={isSaving} onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={isSaving || !name.trim()}
              onClick={() => void handleSave()}
            >
              {isSaving ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving…
                </>
              ) : (
                "Save"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <NewGroupDialog
        open={newGroupOpen}
        parentLabel={
          selectedGroupPath
            ? selectedGroupPath.split("/").pop() ?? selectedGroupPath
            : "Root"
        }
        onClose={() => setNewGroupOpen(false)}
        onCreate={handleNewGroup}
      />
    </>
  );
}
