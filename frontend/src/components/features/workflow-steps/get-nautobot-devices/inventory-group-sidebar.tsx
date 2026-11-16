"use client";

import { useCallback, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Folder, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { InventoryGroupNode, SavedInventory } from "./types/saved-inventory";
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
  collapsedIds: ReadonlySet<string>;
  onToggleCollapse: (id: string) => void;
}

function GroupRow({
  node,
  depth,
  inventories,
  selectedGroupId,
  onSelectGroup,
  collapsedIds,
  onToggleCollapse,
}: GroupRowProps) {
  const count = countInventoriesInGroup(inventories, node.path);
  const isSelected = selectedGroupId === node.id;
  const hasChildren = node.children.length > 0;
  const isExpanded = !collapsedIds.has(node.id);

  return (
    <div>
      <button
        className={cn(
          "flex w-full items-center gap-1 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
          isSelected ? "bg-step-surface text-step-surface-foreground" : "hover:bg-muted",
        )}
        style={{ paddingLeft: `${8 + depth * 12}px` }}
        type="button"
        onClick={() => onSelectGroup(node)}
      >
        {hasChildren ? (
          isExpanded ? (
            <ChevronDown
              className="h-3 w-3 shrink-0 text-muted-foreground"
              aria-hidden
              onClick={(event) => {
                event.stopPropagation();
                onToggleCollapse(node.id);
              }}
            />
          ) : (
            <ChevronRight
              className="h-3 w-3 shrink-0 text-muted-foreground"
              aria-hidden
              onClick={(event) => {
                event.stopPropagation();
                onToggleCollapse(node.id);
              }}
            />
          )
        ) : (
          <span className="inline-block w-3 shrink-0" />
        )}
        <Folder className="h-3.5 w-3.5 shrink-0 text-step" aria-hidden />
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
              collapsedIds={collapsedIds}
              onToggleCollapse={onToggleCollapse}
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

  // Folders are expanded by default; selecting a folder never changes the
  // tree. Only the chevron collapses/expands a folder.
  const [collapsedIds, setCollapsedIds] = useState<ReadonlySet<string>>(() => new Set());
  const onToggleCollapse = useCallback((id: string) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    <div className={cn("flex min-h-0 flex-col border-r border-border bg-card", className)}>
      <div className="border-b border-border px-3 py-2">
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
          collapsedIds={collapsedIds}
          onToggleCollapse={onToggleCollapse}
        />
      </div>
      {showNewGroupButton && onNewGroup ? (
        <div className="border-t border-border p-2">
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
