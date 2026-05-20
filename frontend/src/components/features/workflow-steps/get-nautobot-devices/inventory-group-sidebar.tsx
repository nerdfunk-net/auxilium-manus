"use client";

import { useMemo } from "react";
import { ChevronDown, ChevronRight, Folder, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { InventoryGroupNode, SavedInventory } from "./types/saved-inventory";
import { ROOT_GROUP_ID } from "./types/saved-inventory";
import { buildGroupTree, countInventoriesInGroup } from "./utils/inventory-groups";

interface InventoryGroupSidebarProps {
  groupPaths: string[];
  inventories: SavedInventory[];
  selectedGroupId: string;
  onSelectGroup: (node: InventoryGroupNode) => void;
  onNewGroup?: () => void;
  showNewGroupButton?: boolean;
  className?: string;
}

interface GroupRowProps {
  node: InventoryGroupNode;
  depth: number;
  inventories: SavedInventory[];
  selectedGroupId: string;
  onSelectGroup: (node: InventoryGroupNode) => void;
  expandedIds: Set<string>;
}

function GroupRow({
  node,
  depth,
  inventories,
  selectedGroupId,
  onSelectGroup,
  expandedIds,
}: GroupRowProps) {
  const count = countInventoriesInGroup(inventories, node.path);
  const isSelected = selectedGroupId === node.id;
  const hasChildren = node.children.length > 0;
  const isExpanded = expandedIds.has(node.id) || isSelected;

  return (
    <div>
      <button
        className={cn(
          "flex w-full items-center gap-1 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
          isSelected ? "bg-teal-50 text-teal-900" : "hover:bg-muted",
        )}
        style={{ paddingLeft: `${8 + depth * 12}px` }}
        type="button"
        onClick={() => onSelectGroup(node)}
      >
        {hasChildren ? (
          isExpanded ? (
            <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
          )
        ) : (
          <span className="inline-block w-3 shrink-0" />
        )}
        <Folder className="h-3.5 w-3.5 shrink-0 text-teal-500" aria-hidden />
        <span className="min-w-0 flex-1 truncate font-medium">{node.name}</span>
        <span className="shrink-0 text-[10px] text-muted-foreground">{count}</span>
      </button>
      {hasChildren && isExpanded
        ? node.children.map((child) => (
            <GroupRow
              key={child.id}
              node={child}
              depth={depth + 1}
              inventories={inventories}
              selectedGroupId={selectedGroupId}
              onSelectGroup={onSelectGroup}
              expandedIds={expandedIds}
            />
          ))
        : null}
    </div>
  );
}

export function InventoryGroupSidebar({
  groupPaths,
  inventories,
  selectedGroupId,
  onSelectGroup,
  onNewGroup,
  showNewGroupButton = true,
  className,
}: InventoryGroupSidebarProps) {
  const tree = useMemo(() => buildGroupTree(groupPaths), [groupPaths]);

  const expandedIds = useMemo(() => {
    const ids = new Set<string>();
    if (selectedGroupId === ROOT_GROUP_ID) return ids;
    const segments = selectedGroupId.split("/").filter(Boolean);
    let path = "";
    for (const segment of segments) {
      path = path ? `${path}/${segment}` : segment;
      ids.add(path);
    }
    return ids;
  }, [selectedGroupId]);

  return (
    <div className={cn("flex min-h-0 flex-col border-r border-slate-200 bg-white", className)}>
      <div className="border-b border-slate-200 px-3 py-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Groups
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <GroupRow
          node={tree}
          depth={0}
          inventories={inventories}
          selectedGroupId={selectedGroupId}
          onSelectGroup={onSelectGroup}
          expandedIds={expandedIds}
        />
      </div>
      {showNewGroupButton && onNewGroup ? (
        <div className="border-t border-slate-200 p-2">
          <Button
            className="h-8 w-full gap-1.5 text-xs"
            size="sm"
            type="button"
            variant="ghost"
            onClick={onNewGroup}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
            New Group
          </Button>
        </div>
      ) : null}
    </div>
  );
}
