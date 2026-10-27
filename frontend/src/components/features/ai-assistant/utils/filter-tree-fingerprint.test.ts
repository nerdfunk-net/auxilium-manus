import { describe, expect, it } from "vitest";

import type { ConditionTree } from "@/components/features/inventory/types/device-selector";

import { describeConditionTree } from "./describe-condition-tree";
import { filterTreeFingerprint } from "./filter-tree-fingerprint";

const tree = (id: string, value = "City A"): ConditionTree => ({
  type: "root",
  internalLogic: "AND",
  items: [
    { id, field: "location", operator: "equals", value },
    {
      id: `${id}-g`,
      type: "group",
      logic: "NOT",
      internalLogic: "OR",
      items: [{ id: `${id}-c`, field: "tag", operator: "equals", value: "lab" }],
    },
  ],
});

describe("filterTreeFingerprint", () => {
  it("ignores the random ids", () => {
    expect(filterTreeFingerprint(tree("a"))).toBe(filterTreeFingerprint(tree("b")));
  });

  it("changes with a value, a logic or a group", () => {
    const base = filterTreeFingerprint(tree("a"));

    expect(filterTreeFingerprint(tree("a", "City B"))).not.toBe(base);
    expect(filterTreeFingerprint({ ...tree("a"), internalLogic: "OR" })).not.toBe(base);
    expect(filterTreeFingerprint({ ...tree("a"), items: tree("a").items.slice(0, 1) })).not.toBe(
      base,
    );
  });
});

describe("describeConditionTree", () => {
  it("indents groups and says NOT", () => {
    expect(describeConditionTree(tree("a"))).toEqual([
      "Match AND of:",
      "  location equals City A",
      "  NOT group, match OR:",
      "    tag equals lab",
    ]);
  });

  it("spells operators with spaces", () => {
    const lines = describeConditionTree({
      type: "root",
      internalLogic: "AND",
      items: [{ id: "1", field: "ip_prefix", operator: "within_include", value: "10.0.0.0/8" }],
    });

    expect(lines[1]).toBe("  ip_prefix within include 10.0.0.0/8");
  });
});

describe("depth caps", () => {
  const deep = (levels: number): ConditionTree => {
    let node: ConditionTree["items"][number] = {
      id: "leaf",
      field: "name",
      operator: "equals",
      value: "needle",
    };
    for (let i = 0; i < levels; i += 1) {
      node = { id: String(i), type: "group", logic: "AND", internalLogic: "AND", items: [node] };
    }
    return { type: "root", internalLogic: "AND", items: [node] };
  };

  it("describes a very deep tree without recursing forever", () => {
    const lines = describeConditionTree(deep(5000));

    expect(lines.length).toBeLessThan(30);
    expect(lines.join("\n")).toContain("deeper groups omitted");
    expect(lines.join("\n")).not.toContain("needle");
  });

  it("fingerprints a very deep tree", () => {
    expect(filterTreeFingerprint(deep(5000))).toMatch(/^\d+:\d+$/);
  });
});
