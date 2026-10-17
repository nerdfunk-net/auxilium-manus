import { describe, expect, it } from "vitest";

import type { CanvasGroup, PersistedCanvasNode } from "../types/workflow-canvas";
import { validateGroupBoundary } from "./canvas-group-boundary";

function node(id: string, parentId?: string) {
  return {
    id,
    type: "workflowNode",
    position: { x: 0, y: 0 },
    parentId,
    data: { kind: "log-message", title: id },
  } as unknown as PersistedCanvasNode;
}

function group(id: string, nodeIds: string[]): CanvasGroup {
  return { id, title: id, nodeIds, position: { x: 0, y: 0 }, parentGroupId: null };
}

const NODES = ["A", "B", "C", "D"].map((id) => node(id));

describe("validateGroupBoundary", () => {
  it("accepts any selection of two or more steps (no chain/cycle rule)", () => {
    expect(validateGroupBoundary(["A", "B", "C"], [], NODES).valid).toBe(true);
  });

  it("rejects fewer than two steps", () => {
    const result = validateGroupBoundary(["A"], [], NODES);
    expect(result.valid).toBe(false);
    expect(result.reason).toMatch(/at least two/i);
  });

  it("rejects steps that already belong to a group", () => {
    const result = validateGroupBoundary(["A", "B"], [group("g", ["B", "C"])], NODES);
    expect(result.valid).toBe(false);
    expect(result.reason).toMatch(/already belong/i);
  });

  it("rejects steps inside a background", () => {
    const nodes = [node("A"), node("B", "bg")];
    const result = validateGroupBoundary(["A", "B"], [], nodes);
    expect(result.valid).toBe(false);
    expect(result.reason).toMatch(/background/i);
  });
});
