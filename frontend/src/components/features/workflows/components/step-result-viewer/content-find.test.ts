import { describe, expect, it } from "vitest";

import { findMatches, wrapMatchIndex } from "./content-find";

describe("findMatches", () => {
  it("returns no matches for an empty query", () => {
    expect(findMatches("hello", "")).toEqual([]);
  });

  it("finds case-insensitive non-overlapping matches with original lengths", () => {
    expect(findMatches("AaaA", "aa")).toEqual([
      { start: 0, length: 2 },
      { start: 2, length: 2 },
    ]);
    expect(findMatches("Hostname: edge-1", "HOST")).toEqual([{ start: 0, length: 4 }]);
  });

  it("does not report overlapping matches", () => {
    expect(findMatches("aaa", "aa")).toEqual([{ start: 0, length: 2 }]);
  });

  it("treats regex metacharacters as literal text", () => {
    expect(findMatches("a.b aXb", "a.b")).toEqual([{ start: 0, length: 3 }]);
  });
});

describe("wrapMatchIndex", () => {
  it("returns 0 when there are no matches", () => {
    expect(wrapMatchIndex(3, 0)).toBe(0);
  });

  it("wraps forwards and backwards", () => {
    expect(wrapMatchIndex(2, 2)).toBe(0);
    expect(wrapMatchIndex(-1, 3)).toBe(2);
  });
});
