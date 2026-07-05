"use client";

import { useState, useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, FileText, ChevronDown, ChevronRight } from "lucide-react";

import type { ConditionTree } from "../types/device-selector";
import { GroupTreePanel } from "../components/group-tree-panel";
import { generateConditionTreeAscii } from "../utils/group-utils";

interface SavedInventorySummary {
  id: number;
  name: string;
  scope: string;
  group_path?: string | null;
}

interface SaveInventoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (
    name: string,
    description: string,
    scope: string,
    isUpdate: boolean,
    existingId?: number,
    group_path?: string | null,
  ) => Promise<boolean>;
  isSaving: boolean;
  savedInventories: SavedInventorySummary[];
  currentConditionTree: ConditionTree;
  initialName?: string;
  initialDescription?: string;
  initialGroupPath?: string | null;
}

interface SaveInventoryFormProps {
  onClose: () => void;
  onSave: SaveInventoryModalProps["onSave"];
  isSaving: boolean;
  savedInventories: SavedInventorySummary[];
  currentConditionTree: ConditionTree;
  initialName?: string;
  initialDescription?: string;
  initialGroupPath?: string | null;
}

function SaveInventoryForm({
  onClose,
  onSave,
  isSaving,
  savedInventories,
  currentConditionTree,
  initialName,
  initialDescription,
  initialGroupPath,
}: SaveInventoryFormProps) {
  const [name, setName] = useState(initialName ?? "");
  const [description, setDescription] = useState(initialDescription ?? "");
  const [scope, setScope] = useState<string>("global");
  const [selectedGroup, setSelectedGroup] = useState<string | null>(
    initialGroupPath ?? null,
  );
  const [localGroupPaths, setLocalGroupPaths] = useState<string[]>([]);
  const [showTree, setShowTree] = useState(false);
  const [showOverwriteConfirm, setShowOverwriteConfirm] = useState(false);
  const [inventoryToOverwrite, setInventoryToOverwrite] =
    useState<SavedInventorySummary | null>(null);

  const inventoriesInGroup = useMemo(
    () =>
      savedInventories.filter(
        (inv) => (inv.group_path ?? "") === (selectedGroup ?? ""),
      ),
    [savedInventories, selectedGroup],
  );

  const treeAscii = useMemo(
    () => generateConditionTreeAscii(currentConditionTree),
    [currentConditionTree],
  );

  const handleCreateGroup = (parentPath: string | null, groupName: string) => {
    const newPath = parentPath ? `${parentPath}/${groupName}` : groupName;
    setLocalGroupPaths((prev) => [...prev, newPath]);
    setSelectedGroup(newPath);
  };

  const handleSaveClick = async () => {
    if (!name.trim()) {
      return;
    }

    const existingInventory = savedInventories.find((inv) => inv.name === name.trim());
    if (existingInventory && !showOverwriteConfirm) {
      setInventoryToOverwrite(existingInventory);
      setShowOverwriteConfirm(true);
      return;
    }

    const success = await onSave(
      name.trim(),
      description,
      scope,
      Boolean(existingInventory),
      existingInventory?.id,
      selectedGroup,
    );

    if (success) {
      onClose();
    }
  };

  if (showOverwriteConfirm) {
    return (
      <div className="flex flex-1 flex-col gap-4 p-6">
        <div className="rounded border-l-4 border-yellow-400 bg-yellow-50 p-4">
          <div className="flex gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-yellow-500" />
            <p className="text-sm text-yellow-800">
              An inventory named{" "}
              <strong>&quot;{inventoryToOverwrite?.name}&quot;</strong> already exists. Do
              you want to overwrite it?
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button
            onClick={() => {
              setShowOverwriteConfirm(false);
              setInventoryToOverwrite(null);
            }}
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button disabled={isSaving} onClick={handleSaveClick} type="button">
            {isSaving ? "Overwriting..." : "Yes, Overwrite"}
          </Button>
        </DialogFooter>
      </div>
    );
  }

  return (
    <>
      <div
        className="flex min-h-0 flex-1 gap-0"
        style={{ minHeight: "280px", maxHeight: "340px" }}
      >
        <div className="w-56 shrink-0 overflow-y-auto border-r p-3">
          <GroupTreePanel
            allowCreate
            extraPaths={localGroupPaths}
            inventories={savedInventories}
            onCreateGroup={handleCreateGroup}
            onSelectGroup={setSelectedGroup}
            selectedGroup={selectedGroup}
          />
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
            Inventories in{" "}
            <span className="text-blue-600">{selectedGroup ?? "Root"}</span>
          </div>
          {inventoriesInGroup.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              No inventories in this group
            </p>
          ) : (
            <div className="space-y-1">
              {inventoriesInGroup.map((inv) => (
                <div
                  className="flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-gray-50"
                  key={inv.id}
                >
                  <FileText className="h-4 w-4 shrink-0 text-gray-400" />
                  <span className="flex-1 truncate text-gray-800">{inv.name}</span>
                  <Badge className="shrink-0 text-xs" variant="secondary">
                    {inv.scope}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="space-y-3 border-t p-4">
        <div className="text-xs font-semibold uppercase tracking-wider text-gray-500">
          General
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label className="text-sm" htmlFor="inv-name">
              Name <span className="text-red-500">*</span>
            </Label>
            <Input
              className={!name.trim() && name !== "" ? "border-red-300" : ""}
              id="inv-name"
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Windows Servers in Berlin"
              value={name}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm" htmlFor="inv-scope">
              Scope
            </Label>
            <Select disabled={isSaving} onValueChange={setScope} value={scope}>
              <SelectTrigger id="inv-scope">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="global">Global (all users)</SelectItem>
                <SelectItem value="private">Private (only you)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="space-y-1.5">
          <Label className="text-sm" htmlFor="inv-desc">
            Description
          </Label>
          <Textarea
            className="resize-none"
            id="inv-desc"
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe what this filter does..."
            rows={2}
            value={description}
          />
        </div>
        <button
          className="flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700"
          onClick={() => setShowTree((v) => !v)}
          type="button"
        >
          {showTree ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
          {showTree ? "Hide" : "Show"} condition tree
        </button>
        {showTree ? (
          <div className="max-h-40 overflow-x-auto overflow-y-auto whitespace-pre rounded-md bg-slate-900 p-3 font-mono text-xs text-slate-50">
            {treeAscii}
          </div>
        ) : null}
      </div>

      <DialogFooter className="border-t px-6 py-4">
        <Button onClick={onClose} type="button" variant="outline">
          Cancel
        </Button>
        <Button disabled={isSaving || !name.trim()} onClick={handleSaveClick} type="button">
          {isSaving ? "Saving..." : "Save"}
        </Button>
      </DialogFooter>
    </>
  );
}

export function SaveInventoryModal({
  isOpen,
  onClose,
  onSave,
  isSaving,
  savedInventories,
  currentConditionTree,
  initialName,
  initialDescription,
  initialGroupPath,
}: SaveInventoryModalProps) {
  const formKey = `${initialName ?? ""}|${initialDescription ?? ""}|${initialGroupPath ?? ""}`;

  return (
    <Dialog onOpenChange={(open) => !open && onClose()} open={isOpen}>
      <DialogContent className="flex max-h-[88vh] max-w-5xl flex-col gap-0 p-0 sm:max-w-5xl">
        <DialogHeader className="border-b px-6 pb-4 pt-6">
          <DialogTitle>Save Inventory Filter</DialogTitle>
        </DialogHeader>

        {isOpen ? (
          <SaveInventoryForm
            currentConditionTree={currentConditionTree}
            initialDescription={initialDescription}
            initialGroupPath={initialGroupPath}
            initialName={initialName}
            isSaving={isSaving}
            key={formKey}
            onClose={onClose}
            onSave={onSave}
            savedInventories={savedInventories}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
