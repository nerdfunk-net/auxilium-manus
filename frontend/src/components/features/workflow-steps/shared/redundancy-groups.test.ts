import { describe, expect, it } from "vitest";

import {
  DEFAULT_REDUNDANCY_GROUPS_CONFIG,
  REDUNDANCY_PATTERN_MAX_LENGTH,
  parseRedundancyGroupsConfig,
  redundancyGroupsForSave,
  redundancyNameExamples,
  redundancyPatternProblem,
} from "./redundancy-groups";

describe("redundancyPatternProblem", () => {
  it("accepts patterns with {next} once and optional {protocol}", () => {
    expect(redundancyPatternProblem("hsrp-{next}")).toBeNull();
    expect(redundancyPatternProblem("{protocol}-grp-{next}")).toBeNull();
  });

  it("refuses a pattern longer than the backend accepts", () => {
    const longest = "a".repeat(REDUNDANCY_PATTERN_MAX_LENGTH - "{next}".length) + "{next}";
    expect(redundancyPatternProblem(longest)).toBeNull();
    expect(redundancyPatternProblem(`a${longest}`)).toMatch(/too long/);
  });

  it("refuses patterns the backend would reject", () => {
    for (const bad of ["", "  ", "hsrp", "a-{next}-{next}", "a/{next}", "x-{next}-{foo}", "a}{next}"]) {
      expect(redundancyPatternProblem(bad), bad).not.toBeNull();
    }
  });
});

describe("redundancyNameExamples", () => {
  it("shows the first names the schema would give", () => {
    expect(redundancyNameExamples("hsrp-{next}")).toBe("hsrp-1, hsrp-2, hsrp-3");
    expect(redundancyNameExamples("{protocol}-g{next}")).toBe("hsrp-g1, hsrp-g2, hsrp-g3");
  });
});

describe("parseRedundancyGroupsConfig", () => {
  it("returns the defaults for missing or malformed input", () => {
    expect(parseRedundancyGroupsConfig(undefined)).toBe(DEFAULT_REDUNDANCY_GROUPS_CONFIG);
    expect(parseRedundancyGroupsConfig([])).toBe(DEFAULT_REDUNDANCY_GROUPS_CONFIG);
    expect(DEFAULT_REDUNDANCY_GROUPS_CONFIG).toEqual({
      enabled: false,
      name_pattern: "hsrp-{next}",
      status: "Active",
    });
  });

  it("keeps valid values and falls back for blank ones", () => {
    expect(
      parseRedundancyGroupsConfig({ enabled: true, name_pattern: "g-{next}", status: "Planned" }),
    ).toEqual({ enabled: true, name_pattern: "g-{next}", status: "Planned" });
    expect(parseRedundancyGroupsConfig({ enabled: "yes", name_pattern: " ", status: 3 })).toEqual(
      DEFAULT_REDUNDANCY_GROUPS_CONFIG,
    );
  });
});

describe("redundancyGroupsForSave", () => {
  const on = { enabled: true, name_pattern: " g-{next} ", status: "Active" };

  it("trims the pattern and keeps enabled with the nautobot_origin source", () => {
    expect(redundancyGroupsForSave(on, "nautobot_origin")).toEqual({
      enabled: true,
      name_pattern: "g-{next}",
      status: "Active",
    });
  });

  it("switches the feature off for other sources (the backend refuses it there)", () => {
    expect(redundancyGroupsForSave(on, "manual").enabled).toBe(false);
    expect(redundancyGroupsForSave(on, "parsed_list").enabled).toBe(false);
  });
});
