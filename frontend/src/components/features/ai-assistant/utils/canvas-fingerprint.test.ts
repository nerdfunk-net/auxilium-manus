import { describe, expect, it } from "vitest";

import { canvasFingerprint } from "./canvas-fingerprint";

const node = (id: string, config: Record<string, unknown> = {}, x = 0) => ({
  id,
  position: { x, y: 0 },
  selected: false,
  data: { kind: "k", title: "T", pluginConfig: config },
});
const edge = { source: "a", sourceHandle: "success", target: "b" };

describe("canvasFingerprint", () => {
  it("is stable for identical canvases", () => {
    expect(canvasFingerprint([node("a"), node("b")], [edge])).toBe(
      canvasFingerprint([node("a"), node("b")], [edge]),
    );
  });

  it("ignores position and selection", () => {
    expect(canvasFingerprint([node("a", {}, 0)], [])).toBe(
      canvasFingerprint([{ ...node("a", {}, 500), selected: true }], []),
    );
  });

  it("changes when a config, a node or an edge changes", () => {
    const base = canvasFingerprint([node("a", { x: 1 }), node("b")], [edge]);

    expect(
      canvasFingerprint([node("a", { x: 2 }), node("b")], [edge]),
    ).not.toBe(base);
    expect(canvasFingerprint([node("a", { x: 1 })], [])).not.toBe(base);
    expect(canvasFingerprint([node("a", { x: 1 }), node("b")], [])).not.toBe(
      base,
    );
  });
});
