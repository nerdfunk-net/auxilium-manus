import type { InventoryGroupNode, SavedInventory } from "../types/saved-inventory";
import { ROOT_GROUP_ID } from "../types/saved-inventory";

export function buildGroupTree(groupPaths: string[]): InventoryGroupNode {
  const root: InventoryGroupNode = {
    id: ROOT_GROUP_ID,
    name: "Root",
    path: null,
    children: [],
  };

  const sorted = [...groupPaths].sort(
    (a, b) => a.split("/").length - b.split("/").length || a.localeCompare(b),
  );

  for (const fullPath of sorted) {
    if (!fullPath.trim()) continue;
    insertGroupPath(root, fullPath);
  }

  sortGroupChildren(root);
  return root;
}

function insertGroupPath(root: InventoryGroupNode, fullPath: string): void {
  const segments = fullPath.split("/").filter(Boolean);
  let current = root;
  let built = "";

  for (const segment of segments) {
    built = built ? `${built}/${segment}` : segment;
    let child = current.children.find((node) => node.id === built);
    if (!child) {
      child = { id: built, name: segment, path: built, children: [] };
      current.children.push(child);
    }
    current = child;
  }
}

function sortGroupChildren(node: InventoryGroupNode): void {
  node.children.sort((a, b) => a.name.localeCompare(b.name));
  for (const child of node.children) {
    sortGroupChildren(child);
  }
}

export function countInventoriesInGroup(
  inventories: SavedInventory[],
  groupPath: string | null,
): number {
  return inventoriesForGroup(inventories, groupPath).length;
}

export function inventoriesForGroup(
  inventories: SavedInventory[],
  groupPath: string | null,
): SavedInventory[] {
  if (groupPath === null) {
    return inventories.filter((inv) => !inv.group_path);
  }
  return inventories.filter((inv) => inv.group_path === groupPath);
}

export function childGroupPath(parentPath: string | null, newName: string): string {
  const trimmed = newName.trim();
  if (!trimmed) return parentPath ?? "";
  if (!parentPath) return trimmed;
  return `${parentPath}/${trimmed}`;
}
