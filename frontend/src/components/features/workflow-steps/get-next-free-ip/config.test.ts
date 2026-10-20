import { describe, expect, it } from "vitest";

import {
  asExpression,
  isWholeNumber,
  numberText,
  stringFromConfig,
  withNumberText,
} from "./config";

describe("get-next-free-ip config helpers", () => {
  it("reads strings and ignores other types", () => {
    expect(stringFromConfig({ a: "x", b: 3 }, "a")).toBe("x");
    expect(stringFromConfig({ b: 3 }, "b")).toBe("");
    expect(stringFromConfig({}, "c")).toBe("");
  });

  it("shows the stored number, the typed text or the default", () => {
    expect(numberText({ count: 4 }, "count", 1)).toBe("4");
    expect(numberText({ count: "" }, "count", 1)).toBe("");
    expect(numberText({}, "count", 1)).toBe("1");
  });

  it("stores whole numbers as numbers and keeps other text as typed", () => {
    expect(withNumberText({}, "count", " 12 ")).toEqual({ count: 12 });
    expect(withNumberText({}, "count", "")).toEqual({ count: "" });
    expect(withNumberText({}, "count", "1.5")).toEqual({ count: "1.5" });
  });

  it("does not mutate the previous config", () => {
    const previous = { count: 1, other: "keep" };
    const next = withNumberText(previous, "count", "2");
    expect(previous).toEqual({ count: 1, other: "keep" });
    expect(next).toEqual({ count: 2, other: "keep" });
  });

  it("wraps a path in braces once", () => {
    expect(asExpression("custom.net")).toBe("{custom.net}");
    expect(asExpression("{custom.net}")).toBe("{custom.net}");
  });

  it("flags number text that is not a whole number", () => {
    expect(isWholeNumber({ count: 3 }, "count", 1)).toBe(true);
    expect(isWholeNumber({}, "count", 1)).toBe(true);
    expect(isWholeNumber({ count: "1.5" }, "count", 1)).toBe(false);
    expect(isWholeNumber({ count: "" }, "count", 1)).toBe(false);
  });
});
