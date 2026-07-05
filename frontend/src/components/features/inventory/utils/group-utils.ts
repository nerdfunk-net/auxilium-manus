import type { ConditionGroup, ConditionItem, ConditionTree } from "../types/device-selector";

export interface GroupTreeNode {
  name: string;
  path: string | null;
  children: GroupTreeNode[];
}

export function buildGroupTree(
  inventories: Array<{ group_path?: string | null }>,
): GroupTreeNode {
  const allPaths = new Set<string>();

  inventories.forEach((inv) => {
    if (inv.group_path) {
      const parts = inv.group_path.split("/").filter(Boolean);
      for (let i = 1; i <= parts.length; i++) {
        allPaths.add(parts.slice(0, i).join("/"));
      }
    }
  });

  const root: GroupTreeNode = { name: "Root", path: null, children: [] };
  const sortedPaths = [...allPaths].sort();

  sortedPaths.forEach((path) => {
    const parts = path.split("/");
    let currentNode = root;

    for (let i = 0; i < parts.length; i++) {
      const partPath = parts.slice(0, i + 1).join("/");
      const existing = currentNode.children.find((c) => c.path === partPath);
      if (existing) {
        currentNode = existing;
      } else {
        const newNode: GroupTreeNode = {
          name: parts[i]!,
          path: partPath,
          children: [],
        };
        currentNode.children.push(newNode);
        currentNode = newNode;
      }
    }
  });

  return root;
}

export function countInventoriesInGroup(
  inventories: Array<{ group_path?: string | null }>,
  groupPath: string | null,
): number {
  const target = groupPath ?? "";
  return inventories.filter((inv) => (inv.group_path ?? "") === target).length;
}

export function generateConditionTreeAscii(conditionTree: ConditionTree): string {
  const lines: string[] = [];
  lines.push(`ROOT (${conditionTree.internalLogic})`);

  if (conditionTree.items.length === 0) {
    lines.push("  (empty)");
    return lines.join("\n");
  }

  const renderItem = (
    item: ConditionItem | ConditionGroup,
    prefix: string,
    isLast: boolean,
    isFirst: boolean,
  ) => {
    const connector = isLast ? "└─ " : "├─ ";
    const extension = isLast ? "   " : "│  ";

    if ("type" in item && item.type === "group") {
      const group = item as ConditionGroup;
      const logicBadge = !isFirst ? `[${group.logic}] ` : "";
      lines.push(`${prefix}${connector}${logicBadge}GROUP (${group.internalLogic})`);

      if (group.items.length === 0) {
        lines.push(`${prefix}${extension}   (empty group)`);
      } else {
        group.items.forEach((subItem, idx) => {
          renderItem(
            subItem,
            `${prefix}${extension}`,
            idx === group.items.length - 1,
            idx === 0,
          );
        });
      }
    } else {
      const condition = item as ConditionItem;
      lines.push(
        `${prefix}${connector}${condition.field} ${condition.operator} "${condition.value}"`,
      );
    }
  };

  conditionTree.items.forEach((item, idx) => {
    renderItem(item, "", idx === conditionTree.items.length - 1, idx === 0);
  });

  return lines.join("\n");
}
