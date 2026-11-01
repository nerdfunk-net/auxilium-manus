import type { Nodes, PhrasingContent, Root } from "mdast";

/**
 * Turns a single newline inside running text into a line break (like `remark-breaks`, without the
 * dependency). CommonMark treats it as a space, which flattens unfenced CLI output or lists of
 * interfaces that a model writes one per line. Code, inline code and tables' structure are other
 * node types and stay as they are; only `text` nodes are split.
 */
export function remarkLineBreaks() {
  return (tree: Root) => {
    splitTextNodes(tree);
  };
}

function splitTextNodes(node: Nodes): void {
  if (!("children" in node)) {
    return;
  }
  const children = node.children as Nodes[];
  const next: Nodes[] = [];
  for (const child of children) {
    if (child.type === "text" && child.value.includes("\n")) {
      next.push(...breakLines(child.value));
      continue;
    }
    splitTextNodes(child);
    next.push(child);
  }
  (node as { children: Nodes[] }).children = next;
}

function breakLines(value: string): PhrasingContent[] {
  const parts = value.split("\n");
  const out: PhrasingContent[] = [];
  parts.forEach((part, index) => {
    if (index > 0) {
      out.push({ type: "break" });
    }
    if (part !== "") {
      out.push({ type: "text", value: part });
    }
  });
  return out;
}
