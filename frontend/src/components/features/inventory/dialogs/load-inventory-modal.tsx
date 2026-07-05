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
import { Badge } from "@/components/ui/badge";
import { Loader2, FileText, ChevronDown, ChevronRight } from "lucide-react";

import type { LogicalCondition, ConditionTree, ConditionItem } from "../types/device-selector";
import { GroupTreePanel } from "../components/group-tree-panel";
import { generateConditionTreeAscii } from "../utils/group-utils";
import { savedTreeToConditionTree } from "../utils/tree-format-converters";

interface SavedInventoryItem {
  id: number;
  name: string;
  description?: string | null;
  conditions: unknown[];
  scope: string;
  group_path?: string | null;
  created_by: string;
}

interface LoadInventoryModalProps {
  isOpen: boolean
  onClose: () => void
  savedInventories: SavedInventoryItem[]
  isLoading: boolean
  onLoad: (id: number) => void
}

function parseInventoryTree(conditions: unknown[]): ConditionTree | null {
  if (!conditions || conditions.length === 0) return null;
  const first = conditions[0];
  if (first && typeof first === "object" && "version" in first && first.version === 2 && "tree" in first) {
    return savedTreeToConditionTree(first.tree);
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

export function LoadInventoryModal({
  isOpen,
  onClose,
  savedInventories,
  isLoading,
  onLoad,
}: LoadInventoryModalProps) {
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null)
  const [selectedInventoryId, setSelectedInventoryId] = useState<number | null>(null)
  const [showTree, setShowTree] = useState(false)

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

  const handleLoad = () => {
    if (selectedInventoryId !== null) {
      onLoad(selectedInventoryId)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={open => !open && onClose()}>
      <DialogContent className="max-w-5xl sm:max-w-5xl max-h-[88vh] flex flex-col p-0 gap-0">
        <DialogHeader className="px-6 pt-6 pb-4 border-b">
          <DialogTitle>Load Saved Inventory</DialogTitle>
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
              style={{ minHeight: '280px', maxHeight: '360px' }}
            >
              {/* Left: Group tree */}
              <div className="w-56 flex-shrink-0 border-r p-3 overflow-y-auto">
                <GroupTreePanel
                  inventories={savedInventories}
                  selectedGroup={selectedGroup}
                  onSelectGroup={group => {
                    setSelectedGroup(group)
                    setSelectedInventoryId(null)
                    setShowTree(false)
                  }}
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
                  <div className="space-y-1">
                    {inventoriesInGroup.map(inv => {
                      const isSelected = selectedInventoryId === inv.id
                      return (
                        <div
                          key={inv.id}
                          className={`flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer text-sm transition-colors ${
                            isSelected
                              ? 'bg-blue-100 text-blue-800 border border-blue-200'
                              : 'hover:bg-gray-50 border border-transparent'
                          }`}
                          onClick={() => {
                            setSelectedInventoryId(inv.id)
                            setShowTree(false)
                          }}
                          onDoubleClick={() => {
                            setSelectedInventoryId(inv.id)
                            onLoad(inv.id)
                          }}
                        >
                          <FileText
                            className={`h-4 w-4 flex-shrink-0 ${isSelected ? 'text-blue-500' : 'text-gray-400'}`}
                          />
                          <span className="flex-1 truncate font-medium">
                            {inv.name}
                          </span>
                          <Badge variant="secondary" className="text-xs flex-shrink-0">
                            {inv.scope}
                          </Badge>
                          <span className="text-xs text-gray-400 flex-shrink-0">
                            {inv.created_by}
                          </span>
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
                        <div className="bg-slate-900 text-slate-50 p-3 rounded-md overflow-x-auto font-mono text-xs whitespace-pre max-h-40 overflow-y-auto">
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
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={handleLoad}
            disabled={selectedInventoryId === null || isLoading}
          >
            Load
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
