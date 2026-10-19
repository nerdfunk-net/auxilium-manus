import { describe, expect, it } from "vitest";

import type { ProjectedCanvasNode } from "../types/workflow-canvas";
import { alignCanvasNodes, type NodeAlignment } from "./node-alignment";

function node(
  id: string,
  x: number,
  y: number,
  size: { width?: number; height?: number } = { width: 100, height: 50 },
  extra: Record<string, unknown> = {},
): ProjectedCanvasNode {
  return { id, position: { x, y }, ...size, ...extra } as unknown as ProjectedCanvasNode;
}

const positions = (nodes: ProjectedCanvasNode[]) =>
  Object.fromEntries(nodes.map((n) => [n.id, n.position]));

describe("alignCanvasNodes", () => {
  const a = node("a", 10, 20, { width: 100, height: 50 });
  const b = node("b", 300, 120, { width: 60, height: 80 });
  const c = node("c", 150, 400, { width: 200, height: 30 });
  const all = [a, b, c];
  const ids = ["a", "b", "c"];

  it.each<[NodeAlignment, Record<string, { x: number; y: number }>]>([
    ["align-left", { a: { x: 10, y: 20 }, b: { x: 10, y: 120 }, c: { x: 10, y: 400 } }],
    // right edges: a=110, b=360, c=350 -> max 360
    ["align-right", { a: { x: 260, y: 20 }, b: { x: 300, y: 120 }, c: { x: 160, y: 400 } }],
    ["align-top", { a: { x: 10, y: 20 }, b: { x: 300, y: 20 }, c: { x: 150, y: 20 } }],
    // bottom edges: a=70, b=200, c=430 -> max 430
    ["align-bottom", { a: { x: 10, y: 380 }, b: { x: 300, y: 350 }, c: { x: 150, y: 400 } }],
  ])("%s", (alignment, expected) => {
    expect(positions(alignCanvasNodes(all, ids, alignment))).toEqual(expected);
  });

  it("centres horizontally on the average centre and keeps y", () => {
    // centres: a=60, b=330, c=250 -> avg 213.333...
    const result = positions(alignCanvasNodes(all, ids, "align-center-horizontal"));
    const avg = (60 + 330 + 250) / 3;
    expect(result.a).toEqual({ x: avg - 50, y: 20 });
    expect(result.b).toEqual({ x: avg - 30, y: 120 });
    expect(result.c).toEqual({ x: avg - 100, y: 400 });
  });

  it("centres vertically on the average centre and keeps x", () => {
    // centres: a=45, b=160, c=415 -> avg 206.666...
    const result = positions(alignCanvasNodes(all, ids, "align-center-vertical"));
    const avg = (45 + 160 + 415) / 3;
    expect(result.a).toEqual({ x: 10, y: avg - 25 });
    expect(result.c).toEqual({ x: 150, y: avg - 15 });
  });

  describe("distribute", () => {
    it("spaces three nodes evenly between the outermost ones, whatever the selection order", () => {
      const nodes = [node("l", 0, 0), node("r", 400, 0), node("m", 50, 0)];
      const result = positions(alignCanvasNodes(nodes, ["r", "m", "l"], "distribute-horizontal"));
      expect(result).toEqual({ l: { x: 0, y: 0 }, m: { x: 200, y: 0 }, r: { x: 400, y: 0 } });
    });

    it("distributes vertically and keeps x", () => {
      const nodes = [node("t", 5, 0), node("b", 9, 300), node("m", 7, 10)];
      const result = positions(alignCanvasNodes(nodes, ["t", "b", "m"], "distribute-vertical"));
      expect(result).toEqual({ t: { x: 5, y: 0 }, m: { x: 7, y: 150 }, b: { x: 9, y: 300 } });
    });

    it.each<NodeAlignment>(["distribute-horizontal", "distribute-vertical"])(
      "%s needs at least three nodes and otherwise changes nothing",
      (alignment) => {
        expect(alignCanvasNodes(all, ["a", "b"], alignment)).toBe(all);
      },
    );
  });

  describe("selection", () => {
    it.each([[[]], [["a"]], [["unknown", "a"]]])(
      "returns the same array when fewer than two nodes are selected (%j)",
      (selection) => {
        expect(alignCanvasNodes(all, selection, "align-left")).toBe(all);
      },
    );

    it("moves only the selected nodes and leaves the others as the same objects", () => {
      const result = alignCanvasNodes(all, ["a", "b"], "align-left");
      expect(result[2]).toBe(c);
      expect(result[0].position.x).toBe(10);
      expect(result[1].position.x).toBe(10);
    });

    it("ignores duplicate ids in the selection", () => {
      const result = alignCanvasNodes(all, ["a", "a", "b"], "align-top");
      expect(result[1].position.y).toBe(20);
    });

    it("does not mutate its input", () => {
      const snapshot = structuredClone(all);
      alignCanvasNodes(all, ids, "align-right");
      expect(all).toEqual(snapshot);
    });
  });

  describe("parented nodes", () => {
    it("aligns in canvas space and writes back parent-relative positions", () => {
      // parent at (1000, 500); child stored relative to it, i.e. absolute (1050, 520).
      const parent = node("p", 1000, 500, { width: 500, height: 500 });
      const child = node("child", 50, 20, { width: 100, height: 50 }, { parentId: "p" });
      const free = node("free", 200, 700);

      const result = alignCanvasNodes([parent, child, free], ["child", "free"], "align-left");

      // min absolute x = 200 -> the child sits at 200 absolute = -800 relative to its parent.
      expect(result.find((n) => n.id === "child")!.position).toEqual({ x: -800, y: 20 });
      expect(result.find((n) => n.id === "free")!.position).toEqual({ x: 200, y: 700 });
      expect(result.find((n) => n.id === "p")).toBe(parent);
    });

    it("treats a missing parent as no offset", () => {
      const orphan = node("o", 40, 0, undefined, { parentId: "gone" });
      const other = node("x", 10, 0);
      const result = alignCanvasNodes([orphan, other], ["o", "x"], "align-left");
      expect(result[0].position.x).toBe(10);
    });
  });

  describe("node size", () => {
    it("prefers the measured size over width/height, then falls back to the default footprint", () => {
      const measured = node("m", 0, 0, { width: 10, height: 10 }, {
        measured: { width: 100, height: 40 },
      });
      const unmeasured = node("u", 0, 0, {});
      const result = alignCanvasNodes([measured, unmeasured], ["m", "u"], "align-right");
      // default footprint is 224 wide, so the right edge is 224
      expect(positions(result)).toEqual({ m: { x: 124, y: 0 }, u: { x: 0, y: 0 } });
    });
  });
});
