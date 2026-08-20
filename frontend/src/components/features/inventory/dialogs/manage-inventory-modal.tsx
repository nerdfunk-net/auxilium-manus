"use client";

import { useState, useMemo, useCallback } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Loader2, ChevronDown, ChevronRight } from "lucide-react";
import { useRenameInventoryGroupMutation } from "@/hooks/queries/use-rename-inventory-group-mutation";

import {
  LogicalCondition,
  ConditionTree,
  ConditionItem,
} from "../types/device-selector";
import { GroupTreePanel } from "../components/group-tree-panel";
import { generateConditionTreeAscii } from "../utils/group-utils";
import { savedTreeToConditionTree } from "../utils/tree-format-converters";
import { ManageInventoryImportExport } from "./manage-inventory-import-export";
import { ManageInventoryRow } from "./manage-inventory-row";

interface SavedInventoryFull {
  id: number;
  name: string;
  description?: string | null;
  conditions: unknown[];
  scope: string;
  group_path?: string | null;
  created_by: string;
  created_at?: string | null;
}

interface ManageInventoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  savedInventories: SavedInventoryFull[];
  isLoading: boolean;
  onUpdate: (
    id: number,
    name: string,
    description: string,
    scope: string,
    group_path?: string | null,
  ) => Promise<void>;
  onDelete: (id: number, name: string) => Promise<void>;
  onExport: (id: number) => Promise<void>;
  onImport: (file: File) => Promise<void>;
}

function parseInventoryTree(conditions: unknown[]): ConditionTree | null {
  if (!conditions || conditions.length === 0) return null;
  const first = conditions[0];
  if (
    first &&
    typeof first === "object" &&
    "version" in first &&
    (first as { version: number }).version === 2 &&
    "tree" in first
  ) {
    return savedTreeToConditionTree((first as { tree: unknown }).tree);
  }
  const items = (conditions as LogicalCondition[])
    .filter((c) => c.field && c.value)
    .map(
      (c): ConditionItem => ({
        id: `${c.field}-${c.value}`,
        field: c.field,
        operator: c.operator,
        value: c.value,
      }),
    );
  return { type: "root", internalLogic: "AND", items };
}

export function ManageInventoryModal({
  isOpen,
  onClose,
  savedInventories,
  isLoading,
  onUpdate,
  onDelete,
  onExport,
  onImport,
}: ManageInventoryModalProps) {
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [localGroupPaths, setLocalGroupPaths] = useState<string[]>([]);
  const [selectedInventoryId, setSelectedInventoryId] = useState<number | null>(null);
  const [showTree, setShowTree] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editScope, setEditScope] = useState<string>("global");
  const [editGroup, setEditGroup] = useState<string>("");

  const allGroupPaths = useMemo(() => {
    const paths = new Set<string>();
    savedInventories.forEach((inv) => {
      if (inv.group_path) paths.add(inv.group_path);
    });
    localGroupPaths.forEach((p) => paths.add(p));
    return [...paths].sort();
  }, [savedInventories, localGroupPaths]);

  const [isDeleting, setIsDeleting] = useState<number | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const [isExporting, setIsExporting] = useState<number | null>(null);
  const [isImporting, setIsImporting] = useState(false);

  const inventoriesInGroup = useMemo(
    () =>
      savedInventories.filter(
        (inv) => (inv.group_path ?? "") === (selectedGroup ?? ""),
      ),
    [savedInventories, selectedGroup],
  );

  const selectedInventory = useMemo(
    () => savedInventories.find((inv) => inv.id === selectedInventoryId) ?? null,
    [savedInventories, selectedInventoryId],
  );

  const selectedTree = useMemo(
    () =>
      selectedInventory
        ? parseInventoryTree(selectedInventory.conditions)
        : null,
    [selectedInventory],
  );

  const treeAscii = useMemo(
    () => (selectedTree ? generateConditionTreeAscii(selectedTree) : ""),
    [selectedTree],
  );

  const startEdit = useCallback((inv: SavedInventoryFull) => {
    setEditingId(inv.id);
    setEditName(inv.name);
    setEditDescription(inv.description ?? "");
    setEditScope(inv.scope);
    setEditGroup(inv.group_path ?? "");
    setDeleteConfirmId(null);
  }, []);

  const cancelEdit = useCallback(() => {
    setEditingId(null);
  }, []);

  const handleCreateGroup = useCallback(
    (parentPath: string | null, groupName: string) => {
      const newPath = parentPath ? `${parentPath}/${groupName}` : groupName;
      setLocalGroupPaths((prev) => [...prev, newPath]);
      setSelectedGroup(newPath);
    },
    [],
  );

  const renameGroupMutation = useRenameInventoryGroupMutation();

  const handleRenameGroup = useCallback(
    async (oldPath: string, newName: string) => {
      const result = await renameGroupMutation.mutateAsync({
        old_path: oldPath,
        new_name: newName,
      });
      if (selectedGroup === oldPath) {
        setSelectedGroup(result.new_path);
      } else if (selectedGroup?.startsWith(oldPath + "/")) {
        setSelectedGroup(result.new_path + selectedGroup.slice(oldPath.length));
      }
      setLocalGroupPaths((prev) =>
        prev.map((p) => {
          if (p === oldPath) return result.new_path;
          if (p.startsWith(oldPath + "/"))
            return result.new_path + p.slice(oldPath.length);
          return p;
        }),
      );
    },
    [renameGroupMutation, selectedGroup],
  );

  const saveEdit = useCallback(
    async (id: number) => {
      if (!editName.trim()) return;
      const groupPath = editGroup.trim() || null;
      await onUpdate(id, editName.trim(), editDescription, editScope, groupPath);
      setEditingId(null);
    },
    [editName, editDescription, editScope, editGroup, onUpdate],
  );

  const confirmDelete = useCallback(
    async (id: number) => {
      const inv = savedInventories.find((i) => i.id === id);
      if (!inv) return;
      setIsDeleting(id);
      try {
        await onDelete(id, inv.name);
        if (selectedInventoryId === id) {
          setSelectedInventoryId(null);
          setShowTree(false);
        }
      } finally {
        setIsDeleting(null);
        setDeleteConfirmId(null);
      }
    },
    [savedInventories, onDelete, selectedInventoryId],
  );

  const handleDeleteClick = useCallback(
    (id: number) => {
      if (deleteConfirmId === id) {
        void confirmDelete(id);
      } else {
        setDeleteConfirmId(id);
        setEditingId(null);
      }
    },
    [deleteConfirmId, confirmDelete],
  );

  const handleExport = useCallback(
    async (id: number) => {
      setIsExporting(id);
      try {
        await onExport(id);
      } finally {
        setIsExporting(null);
      }
    },
    [onExport],
  );

  const handleImport = useCallback(
    async (file: File) => {
      setIsImporting(true);
      try {
        await onImport(file);
      } finally {
        setIsImporting(false);
      }
    },
    [onImport],
  );

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-5xl sm:max-w-5xl max-h-[88vh] flex flex-col p-0 gap-0">
        <DialogHeader className="px-6 pt-6 pb-4 border-b">
          <DialogTitle>Manage Inventories</DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <span className="ml-2 text-sm text-muted-foreground">
              Loading inventories...
            </span>
          </div>
        ) : savedInventories.length === 0 ? (
          <div className="flex-1 flex items-center justify-center py-16">
            <p className="text-muted-foreground text-sm">No saved inventories found.</p>
          </div>
        ) : (
          <>
            <div
              className="flex flex-1 min-h-0"
              style={{ minHeight: "280px", maxHeight: "380px" }}
            >
              <div className="w-56 flex-shrink-0 border-r p-3 overflow-y-auto">
                <GroupTreePanel
                  inventories={savedInventories}
                  selectedGroup={selectedGroup}
                  onSelectGroup={(group) => {
                    setSelectedGroup(group);
                    setSelectedInventoryId(null);
                    setEditingId(null);
                    setShowTree(false);
                  }}
                  allowContextCreate
                  onCreateGroup={handleCreateGroup}
                  onRenameGroup={handleRenameGroup}
                  extraPaths={localGroupPaths}
                />
              </div>

              <div className="flex-1 overflow-y-auto p-3">
                <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Inventories in{" "}
                  <span className="text-primary">{selectedGroup ?? "Root"}</span>
                </div>
                {inventoriesInGroup.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    No inventories in this group
                  </p>
                ) : (
                  <div className="space-y-2">
                    {inventoriesInGroup.map((inv) => (
                      <ManageInventoryRow
                        key={inv.id}
                        inventory={inv}
                        isSelected={selectedInventoryId === inv.id}
                        isEditing={editingId === inv.id}
                        deleteConfirmId={deleteConfirmId}
                        isDeleting={isDeleting}
                        isExporting={isExporting}
                        editName={editName}
                        editDescription={editDescription}
                        editScope={editScope}
                        editGroup={editGroup}
                        allGroupPaths={allGroupPaths}
                        onSelect={() => {
                          setSelectedInventoryId(inv.id);
                          setShowTree(false);
                        }}
                        onStartEdit={() => startEdit(inv)}
                        onCancelEdit={cancelEdit}
                        onSaveEdit={() => void saveEdit(inv.id)}
                        onEditNameChange={setEditName}
                        onEditDescriptionChange={setEditDescription}
                        onEditScopeChange={setEditScope}
                        onEditGroupChange={setEditGroup}
                        onDeleteClick={() => handleDeleteClick(inv.id)}
                        onConfirmDelete={() => void confirmDelete(inv.id)}
                        onCancelDelete={() => setDeleteConfirmId(null)}
                        onExport={() => void handleExport(inv.id)}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div
              className="border-t p-4 space-y-2 overflow-y-auto flex-shrink-0"
              style={{ height: showTree ? "260px" : "110px" }}
            >
              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                General
              </div>
              {selectedInventory ? (
                <>
                  {selectedInventory.description ? (
                    <p className="text-sm text-foreground">
                      {selectedInventory.description}
                    </p>
                  ) : (
                    <p className="text-sm text-muted-foreground italic">
                      No description
                    </p>
                  )}
                  {selectedTree && (
                    <>
                      <button
                        type="button"
                        className="flex items-center gap-1 text-xs text-primary hover:text-info-foreground font-medium"
                        onClick={() => setShowTree((v) => !v)}
                      >
                        {showTree ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                        {showTree ? "Hide" : "Show"} condition tree
                      </button>
                      {showTree && (
                        <div className="bg-slate-900 text-slate-50 p-3 rounded-md overflow-x-auto font-mono text-xs whitespace-pre max-h-36 overflow-y-auto">
                          {treeAscii}
                        </div>
                      )}
                    </>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground italic">
                  Select an inventory to see its details
                </p>
              )}
            </div>
          </>
        )}

        <DialogFooter className="px-6 py-4 border-t">
          <ManageInventoryImportExport
            isImporting={isImporting}
            onImport={handleImport}
            onClose={onClose}
          />
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
