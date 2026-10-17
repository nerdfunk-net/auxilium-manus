import { describe, expect, it } from "vitest";

import { getDropOffset, toDropPosition } from "./step-drop-offset";

describe("getDropOffset", () => {
  it("centers regular steps on the pointer", () => {
    expect(getDropOffset("show-commands")).toEqual({ x: 160, y: 64 });
  });

  it("uses dedicated offsets for label, background and funnel", () => {
    expect(getDropOffset("label")).toEqual({ x: 100, y: 20 });
    expect(getDropOffset("background")).toEqual({ x: 240, y: 160 });
    expect(getDropOffset("funnel")).toEqual({ x: 20, y: 20 });
  });
});

describe("toDropPosition", () => {
  it("subtracts the per-kind offset from the stored pointer position", () => {
    expect(toDropPosition({ x: 500, y: 300 }, "label")).toEqual({ x: 400, y: 280 });
  });
});
