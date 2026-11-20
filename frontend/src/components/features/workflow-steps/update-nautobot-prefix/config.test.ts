import { describe, expect, it } from "vitest";

import {
  BAD_MODE_PROBLEM,
  INTERFACE_CONFLICT_PROBLEM,
  NO_FIELD_PROBLEM,
  NO_PREFIX_PROBLEM,
  UPDATE_FIELD_KEYS,
  configProblems,
  interfaceModeEnabledPatch,
  locationsModeFromConfig,
} from "./config";

describe("update-nautobot-prefix config helpers", () => {
  it("reports a missing prefix selector and a missing field", () => {
    expect(configProblems({})).toEqual([NO_PREFIX_PROBLEM, NO_FIELD_PROBLEM]);
  });

  it("accepts prefix_id or prefix as the selector", () => {
    expect(
      configProblems({ prefix_id: "{custom.p}", status: "Active" }),
    ).toEqual([]);
    expect(configProblems({ prefix: "10.0.0.0/24", status: "Active" })).toEqual(
      [],
    );
  });

  it("is complete with any single field", () => {
    for (const key of UPDATE_FIELD_KEYS) {
      expect(configProblems({ prefix: "10.0.0.0/24", [key]: "x" })).toEqual([]);
    }
  });

  it("treats whitespace-only values as empty", () => {
    expect(configProblems({ prefix: " ", status: "  " })).toEqual([
      NO_PREFIX_PROBLEM,
      NO_FIELD_PROBLEM,
    ]);
  });

  it("flags an unknown locations mode and defaults an empty one to replace", () => {
    expect(
      configProblems({
        prefix: "10.0.0.0/24",
        status: "A",
        locations_mode: "merge",
      }),
    ).toEqual([BAD_MODE_PROBLEM]);
    expect(locationsModeFromConfig({})).toBe("replace");
    expect(locationsModeFromConfig({ locations_mode: "merge" })).toBe("");
    expect(locationsModeFromConfig({ locations_mode: "add" })).toBe("add");
  });
});

describe("prefixes from interfaces mode", () => {
  it("needs no prefix selector and no field", () => {
    expect(configProblems({ prefixes_from_interfaces: true })).toEqual([]);
    expect(
      configProblems({ prefixes_from_interfaces: "true", dry_run: true }),
    ).toEqual([]);
  });

  it("warns about a field the mode refuses", () => {
    expect(
      configProblems({ prefixes_from_interfaces: true, status: "Active" }),
    ).toEqual([INTERFACE_CONFLICT_PROBLEM]);
  });

  it("clears the refused keys when the mode is switched on", () => {
    const patch = interfaceModeEnabledPatch();
    expect(patch).toMatchObject({
      prefixes_from_interfaces: true,
      locations_mode: "add",
      prefix: "",
      namespace: "",
    });
    expect(configProblems({ prefix: "10.0.0.0/24", ...patch })).toEqual([]);
  });
});
