import { describe, expect, it } from "vitest";

import type { ProjectedCanvasNode } from "../types/workflow-canvas";
import {
  draggableStepIds,
  findGroupNodeAtPoint,
  isPointInClientRect,
} from "./canvas-group-dnd";

function groupNode(id: string, x: number, y: number): ProjectedCanvasNode {
  return {
    id: `__group__${id}`,
    type: "groupNode",
    position: { x, y },
    width: 320,
    height: 128,
    data: { kind: "__canvas-group__", title: id, memberCount: 0, groupId: id, inputPorts: [], outputPorts: [] },
  } as unknown as ProjectedCanvasNode;
}

function step(id: string, type = "workflowNode", parentId?: string): ProjectedCanvasNode {
  return {
    id,
    type,
    position: { x: 0, y: 0 },
    parentId,
    data: { kind: "log-message", title: id },
  } as unknown as ProjectedCanvasNode;
}

describe("findGroupNodeAtPoint", () => {
  const nodes = [groupNode("a", 0, 0), groupNode("b", 200, 50), step("s")];

  it("returns the group id under the point", () => {
    expect(findGroupNodeAtPoint({ x: 10, y: 10 }, nodes)).toBe("a");
  });

  it("returns null outside every group", () => {
    expect(findGroupNodeAtPoint({ x: 900, y: 900 }, nodes)).toBeNull();
  });

  it("picks the topmost (last) group where two overlap", () => {
    expect(findGroupNodeAtPoint({ x: 250, y: 80 }, nodes)).toBe("b");
  });

  it("treats the rect edge as inside", () => {
    expect(findGroupNodeAtPoint({ x: 320, y: 128 }, [groupNode("a", 0, 0)])).toBe("a");
  });

  it("ignores groups that are themselves being dragged", () => {
    expect(findGroupNodeAtPoint({ x: 10, y: 10 }, nodes, new Set(["__group__a"]))).toBeNull();
  });
});

describe("draggableStepIds", () => {
  it("keeps real steps and drops groups, backgrounds and background children", () => {
    const dragged = [
      step("s1"),
      step("lbl", "labelNode"),
      step("bg", "backgroundNode"),
      step("child", "workflowNode", "bg"),
      groupNode("g", 0, 0),
    ];
    expect(draggableStepIds(dragged)).toEqual(["s1", "lbl"]);
  });
});

describe("isPointInClientRect", () => {
  const rect = { left: 10, top: 20, right: 110, bottom: 60 };
  it("is inclusive of edges and false outside", () => {
    expect(isPointInClientRect(10, 20, rect)).toBe(true);
    expect(isPointInClientRect(110, 60, rect)).toBe(true);
    expect(isPointInClientRect(9, 30, rect)).toBe(false);
    expect(isPointInClientRect(50, 61, rect)).toBe(false);
  });
});
