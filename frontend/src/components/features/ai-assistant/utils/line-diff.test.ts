import { describe, expect, it } from "vitest";

import { buildLineDiff } from "./line-diff";

describe("buildLineDiff", () => {
  it("reports additions and removals by line", () => {
    const diff = buildLineDiff("a\nb\nc\n", "a\nB\nc\nd\n");

    expect(diff.added).toBe(2);
    expect(diff.removed).toBe(1);
    expect(
      diff.rows.filter((r) => r.kind === "removed").map((r) => r.text),
    ).toEqual(["b"]);
    expect(
      diff.rows.filter((r) => r.kind === "added").map((r) => r.text),
    ).toEqual(["B", "d"]);
  });

  it("treats everything as added when the editor was empty", () => {
    const diff = buildLineDiff("", "hostname x\nntp server y\n");

    expect(diff.removed).toBe(0);
    expect(diff.added).toBe(2);
  });

  it("collapses long unchanged runs into one gap row", () => {
    const unchanged = Array.from({ length: 30 }, (_, i) => `line ${i}`).join(
      "\n",
    );
    const diff = buildLineDiff(`${unchanged}\nold\n`, `${unchanged}\nnew\n`);

    const gap = diff.rows.find((r) => r.kind === "gap");
    expect(gap?.hidden).toBe(27);
    expect(diff.rows.length).toBeLessThan(12);
  });

  it("returns no changes for identical text", () => {
    const diff = buildLineDiff("same\n", "same\n");

    expect(diff.added + diff.removed).toBe(0);
  });
});
