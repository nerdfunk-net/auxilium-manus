"use client";

import { useState, useMemo, useCallback } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Pencil,
  Trash2,
  X,
  Check,
  Loader2,
  Download,
  Upload,
  FileText,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { useRenameInventoryGroupMutation } from "@/hooks/queries/use-rename-inventory-group-mutation";

import {
  LogicalCondition,
  ConditionTree,
  ConditionItem,
} from "../types/device-selector";
import { GroupTreePanel } from "../components/group-tree-panel";
import { generateConditionTreeAscii } from "../utils/group-utils";
import { savedTreeToConditionTree } from "../utils/tree-format-converters";

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
  isOpen: boolean
  onClose: () => void
  savedInventories: SavedInventoryFull[]
  isLoading: boolean
  onUpdate: (
    id: number,
    name: string,
    description: string,
    scope: string,
    group_path?: string | null
  ) => Promise<void>
  onDelete: (id: number, name: string) => Promise<void>
  onExport: (id: number) => Promise<void>
  onImport: (file: File) => Promise<void>
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
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null)
  const [localGroupPaths, setLocalGroupPaths] = useState<string[]>([])
  const [selectedInventoryId, setSelectedInventoryId] = useState<number | null>(null)
  const [showTree, setShowTree] = useState(false)

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editScope, setEditScope] = useState<string>('global')
  const [editGroup, setEditGroup] = useState<string>("");

  const allGroupPaths = useMemo(() => {
    const paths = new Set<string>()
    savedInventories.forEach(inv => {
      if (inv.group_path) paths.add(inv.group_path)
    })
    localGroupPaths.forEach(p => paths.add(p))
    return [...paths].sort()
  }, [savedInventories, localGroupPaths])

  const [isDeleting, setIsDeleting] = useState<number | null>(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)
  const [isExporting, setIsExporting] = useState<number | null>(null)
  const [isImporting, setIsImporting] = useState(false)

  const inventoriesInGroup = useMemo(
    () =>
      savedInventories.filter(inv => (inv.group_path ?? '') === (selectedGroup ?? '')),
    [savedInventories, selectedGroup]
  )

  const selectedInventory = useMemo(
    () => savedInventories.find(inv => inv.id === selectedInventoryId) ?? null,
    [savedInventories, selectedInventoryId]
  )

  const selectedTree = useMemo(
    () => (selectedInventory ? parseInventoryTree(selectedInventory.conditions) : null),
    [selectedInventory]
  )

  const treeAscii = useMemo(
    () => (selectedTree ? generateConditionTreeAscii(selectedTree) : ''),
    [selectedTree]
  )

  const startEdit = (inv: SavedInventoryFull) => {
    setEditingId(inv.id)
    setEditName(inv.name)
    setEditDescription(inv.description ?? '')
    setEditScope(inv.scope)
    setEditGroup(inv.group_path ?? '')
    setDeleteConfirmId(null)
  }

  const cancelEdit = () => {
    setEditingId(null)
  }

  const handleCreateGroup = useCallback(
    (parentPath: string | null, groupName: string) => {
      const newPath = parentPath ? `${parentPath}/${groupName}` : groupName
      setLocalGroupPaths(prev => [...prev, newPath])
      setSelectedGroup(newPath)
    },
    []
  )

  const renameGroupMutation = useRenameInventoryGroupMutation();

  const handleRenameGroup = useCallback(
    async (oldPath: string, newName: string) => {
      const result = await renameGroupMutation.mutateAsync({
        old_path: oldPath,
        new_name: newName,
      })
      if (selectedGroup === oldPath) {
        setSelectedGroup(result.new_path)
      } else if (selectedGroup?.startsWith(oldPath + '/')) {
        setSelectedGroup(result.new_path + selectedGroup.slice(oldPath.length))
      }
      setLocalGroupPaths(prev =>
        prev.map(p => {
          if (p === oldPath) return result.new_path
          if (p.startsWith(oldPath + '/'))
            return result.new_path + p.slice(oldPath.length)
          return p
        })
      )
    },
    [renameGroupMutation, selectedGroup]
  )

  const saveEdit = async (id: number) => {
    if (!editName.trim()) return
    const groupPath = editGroup.trim() || null
    await onUpdate(id, editName.trim(), editDescription, editScope, groupPath)
    setEditingId(null)
  }

  const handleDeleteClick = (id: number) => {
    if (deleteConfirmId === id) {
      confirmDelete(id)
    } else {
      setDeleteConfirmId(id)
      setEditingId(null)
    }
  }

  const confirmDelete = async (id: number) => {
    const inv = savedInventories.find(i => i.id === id)
    if (!inv) return
    setIsDeleting(id)
    try {
      await onDelete(id, inv.name)
      if (selectedInventoryId === id) {
        setSelectedInventoryId(null)
        setShowTree(false)
      }
    } finally {
      setIsDeleting(null)
      setDeleteConfirmId(null)
    }
  }

  const handleExport = async (id: number) => {
    setIsExporting(id)
    try {
      await onExport(id)
    } finally {
      setIsExporting(null)
    }
  }

  const handleImportClick = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = async e => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (file) {
        setIsImporting(true)
        try {
          await onImport(file)
        } finally {
          setIsImporting(false)
        }
      }
    }
    input.click()
  }

  return (
    <Dialog open={isOpen} onOpenChange={open => !open && onClose()}>
      <DialogContent className="max-w-5xl sm:max-w-5xl max-h-[88vh] flex flex-col p-0 gap-0">
        <DialogHeader className="px-6 pt-6 pb-4 border-b">
          <DialogTitle>Manage Inventories</DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
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
            {/* Main area: group tree (left) + files (right) */}
            <div
              className="flex flex-1 min-h-0"
              style={{ minHeight: '280px', maxHeight: '380px' }}
            >
              {/* Left: Group tree */}
              <div className="w-56 flex-shrink-0 border-r p-3 overflow-y-auto">
                <GroupTreePanel
                  inventories={savedInventories}
                  selectedGroup={selectedGroup}
                  onSelectGroup={group => {
                    setSelectedGroup(group)
                    setSelectedInventoryId(null)
                    setEditingId(null)
                    setShowTree(false)
                  }}
                  allowContextCreate
                  onCreateGroup={handleCreateGroup}
                  onRenameGroup={handleRenameGroup}
                  extraPaths={localGroupPaths}
                />
              </div>

              {/* Right: inventory files */}
              <div className="flex-1 overflow-y-auto p-3">
                <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                  Inventories in{' '}
                  <span className="text-blue-600">{selectedGroup ?? 'Root'}</span>
                </div>
                {inventoriesInGroup.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    No inventories in this group
                  </p>
                ) : (
                  <div className="space-y-2">
                    {inventoriesInGroup.map(inv => {
                      const isSelected = selectedInventoryId === inv.id
                      const isEditing = editingId === inv.id

                      return (
                        <div
                          key={inv.id}
                          className={`border rounded-lg transition-colors ${
                            isSelected && !isEditing
                              ? 'border-blue-200 bg-blue-50'
                              : 'border-gray-200 bg-white'
                          }`}
                        >
                          {isEditing ? (
                            <div className="p-3 space-y-3">
                              <div className="grid grid-cols-2 gap-3">
                                <div className="space-y-1">
                                  <Label className="text-xs">Name</Label>
                                  <Input
                                    value={editName}
                                    onChange={e => setEditName(e.target.value)}
                                    className="h-7 text-sm"
                                  />
                                </div>
                                <div className="space-y-1">
                                  <Label className="text-xs">Scope</Label>
                                  <Select
                                    value={editScope}
                                    onValueChange={setEditScope}
                                  >
                                    <SelectTrigger className="h-7 text-sm">
                                      <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                      <SelectItem value="global">Global</SelectItem>
                                      <SelectItem value="private">Private</SelectItem>
                                    </SelectContent>
                                  </Select>
                                </div>
                              </div>
                              <div className="space-y-1">
                                <Label className="text-xs">Description</Label>
                                <Textarea
                                  value={editDescription}
                                  onChange={e => setEditDescription(e.target.value)}
                                  rows={1}
                                  className="min-h-[36px] text-sm resize-none"
                                />
                              </div>
                              <div className="space-y-1">
                                <Label className="text-xs">Group</Label>
                                <Select
                                  onValueChange={(value) =>
                                    setEditGroup(value === "__root__" ? "" : value)
                                  }
                                  value={editGroup || "__root__"}
                                >
                                  <SelectTrigger className="h-7 text-sm">
                                    <SelectValue placeholder="Root (no group)" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="__root__">Root (no group)</SelectItem>
                                    {allGroupPaths.map((path) => (
                                      <SelectItem key={path} value={path}>
                                        {path}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </div>
                              <div className="flex justify-end gap-2">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={cancelEdit}
                                  className="h-7 text-xs"
                                >
                                  <X className="h-3 w-3 mr-1" /> Cancel
                                </Button>
                                <Button
                                  size="sm"
                                  onClick={() => saveEdit(inv.id)}
                                  className="h-7 text-xs"
                                >
                                  <Check className="h-3 w-3 mr-1" /> Save
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <div
                              className="flex items-center gap-2 px-3 py-2 cursor-pointer"
                              onClick={() => {
                                setSelectedInventoryId(inv.id)
                                setShowTree(false)
                              }}
                            >
                              <FileText
                                className={`h-4 w-4 flex-shrink-0 ${isSelected ? 'text-blue-500' : 'text-gray-400'}`}
                              />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="text-sm font-medium truncate">
                                    {inv.name}
                                  </span>
                                  <Badge
                                    variant="secondary"
                                    className="text-xs flex-shrink-0"
                                  >
                                    {inv.scope}
                                  </Badge>
                                </div>
                                <div className="text-xs text-gray-400">
                                  {inv.created_by}
                                  {inv.created_at && (
                                    <>
                                      {' '}
                                      &bull;{' '}
                                      {new Date(inv.created_at).toLocaleDateString()}
                                    </>
                                  )}
                                </div>
                              </div>

                              {/* Action buttons */}
                              <div className="flex items-center gap-1 flex-shrink-0">
                                {deleteConfirmId === inv.id ? (
                                  <div className="flex items-center gap-1 bg-red-50 px-2 py-1 rounded border border-red-200">
                                    <span className="text-xs text-red-600 font-medium">
                                      Sure?
                                    </span>
                                    <Button
                                      size="sm"
                                      variant="destructive"
                                      className="h-6 px-2 text-xs"
                                      onClick={e => {
                                        e.stopPropagation()
                                        confirmDelete(inv.id)
                                      }}
                                      disabled={isDeleting === inv.id}
                                    >
                                      {isDeleting === inv.id ? (
                                        <Loader2 className="h-3 w-3 animate-spin" />
                                      ) : (
                                        'Yes'
                                      )}
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className="h-6 w-6 p-0"
                                      onClick={e => {
                                        e.stopPropagation()
                                        setDeleteConfirmId(null)
                                      }}
                                    >
                                      <X className="h-3 w-3" />
                                    </Button>
                                  </div>
                                ) : (
                                  <>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className="h-7 w-7 p-0 hover:bg-gray-100"
                                      title="Edit"
                                      onClick={e => {
                                        e.stopPropagation()
                                        startEdit(inv)
                                      }}
                                    >
                                      <Pencil className="h-3.5 w-3.5" />
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className="h-7 w-7 p-0 text-blue-600 hover:bg-blue-50"
                                      title="Export"
                                      onClick={e => {
                                        e.stopPropagation()
                                        handleExport(inv.id)
                                      }}
                                      disabled={isExporting === inv.id}
                                    >
                                      {isExporting === inv.id ? (
                                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                      ) : (
                                        <Download className="h-3.5 w-3.5" />
                                      )}
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className="h-7 w-7 p-0 text-red-600 hover:bg-red-50"
                                      title="Delete"
                                      onClick={e => {
                                        e.stopPropagation()
                                        handleDeleteClick(inv.id)
                                      }}
                                    >
                                      <Trash2 className="h-3.5 w-3.5" />
                                    </Button>
                                  </>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* General panel — fixed height per state so clicking an inventory never shifts the layout */}
            <div
              className="border-t p-4 space-y-2 overflow-y-auto flex-shrink-0"
              style={{ height: showTree ? '260px' : '110px' }}
            >
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                General
              </div>
              {selectedInventory ? (
                <>
                  {selectedInventory.description ? (
                    <p className="text-sm text-gray-700">
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
                        className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 font-medium"
                        onClick={() => setShowTree(v => !v)}
                      >
                        {showTree ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                        {showTree ? 'Hide' : 'Show'} condition tree
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
          <div className="flex items-center justify-between w-full">
            <Button
              variant="outline"
              onClick={handleImportClick}
              disabled={isImporting}
              className="flex items-center gap-2"
            >
              {isImporting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4" />
              )}
              Import Inventory
            </Button>
            <Button variant="outline" onClick={onClose}>
              Close
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
