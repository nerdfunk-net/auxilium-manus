import { describe, expect, it } from "vitest";

import type { HelpSection } from "../constants/help-content";
import { filterHelpSections } from "./help-search";

const SECTIONS: readonly HelpSection[] = [
  {
    id: "a",
    title: "Alpha",
    summary: "Routing things",
    tools: [
      {
        name: "get_routes",
        description: "Reads routes",
        questions: ["Which route?"],
      },
      {
        name: "get_acl",
        description: "Reads filters",
        questions: ["Any deny?"],
      },
    ],
  },
  {
    id: "b",
    title: "Beta",
    summary: "Other",
    requirement: "Needs Genie",
    tools: [{ name: "learn", description: "Learns", questions: ["Learn BGP"] }],
  },
];

describe("filterHelpSections", () => {
  it("returns everything for a blank query", () => {
    expect(filterHelpSections(SECTIONS, "  ")).toBe(SECTIONS);
  });

  it("matches tool text, case-insensitively, keeping only matching tools", () => {
    const result = filterHelpSections(SECTIONS, "DENY");
    expect(result.map((s) => s.id)).toEqual(["a"]);
    expect(result[0].tools.map((t) => t.name)).toEqual(["get_acl"]);
  });

  it("keeps all tools when the group text matches", () => {
    const result = filterHelpSections(SECTIONS, "genie");
    expect(result.map((s) => s.id)).toEqual(["b"]);
    expect(result[0].tools).toHaveLength(1);
    expect(filterHelpSections(SECTIONS, "routing")[0].tools).toHaveLength(2);
  });

  it("requires every word and returns nothing without a match", () => {
    expect(filterHelpSections(SECTIONS, "reads deny")[0].tools).toHaveLength(1);
    expect(filterHelpSections(SECTIONS, "zzz")).toEqual([]);
  });
});
