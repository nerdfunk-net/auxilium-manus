import { describe, expect, it } from "vitest";

import type { PersistedCanvasNode } from "../types/workflow-canvas";
import { resolveContainment } from "./canvas-containment";

function background(id: string, x: number, y: number, width: number, height: number) {
  return {
    id,
    type: "backgroundNode",
    position: { x, y },
    width,
    height,
    data: { kind: "background", title: id },
  } as unknown as PersistedCanvasNode;
}

// Shaped like the synthetic Step Group node React Flow reports on drag-end.
function groupSubject(position: { x: number; y: number }, parentId?: string) {
  return { id: "__group__g1", position, parentId, width: 320, height: 128 };
}

const BG = background("bg", 1000, 500, 800, 600);

describe("resolveContainment with a Step Group subject", () => {
  it("attaches a group dropped onto a background, with a parent-relative position", () => {
    const result = resolveContainment(groupSubject({ x: 1100, y: 600 }), [BG]);
    expect(result).toEqual({ parentId: "bg", position: { x: 100, y: 100 } });
  });

  it("detaches a group dragged off its background, back to absolute coordinates", () => {
    // relative (-900, -400) from bg at (1000, 500) => absolute (100, 100)
    const result = resolveContainment(groupSubject({ x: -900, y: -400 }, "bg"), [BG]);
    expect(result).toEqual({ parentId: undefined, position: { x: 100, y: 100 } });
  });

  it("keeps a group attached when it moves within the same background", () => {
    const result = resolveContainment(groupSubject({ x: 50, y: 40 }, "bg"), [BG]);
    expect(result).toEqual({ parentId: "bg", position: { x: 50, y: 40 } });
  });

  it("leaves a group on empty canvas unparented", () => {
    const result = resolveContainment(groupSubject({ x: 0, y: 0 }), [BG]);
    expect(result).toEqual({ parentId: undefined, position: { x: 0, y: 0 } });
  });
});
