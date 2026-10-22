import { describe, expect, it } from "vitest";

import { NO_FIELD_PROBLEM, UPDATE_FIELD_KEYS, configProblems } from "./config";

describe("update-nautobot-ip config helpers", () => {
  it("reports a missing ip_id and a missing field", () => {
    expect(configProblems({})).toEqual(["ip_id is not configured", NO_FIELD_PROBLEM]);
  });

  it("is complete with an id and any single field", () => {
    for (const key of UPDATE_FIELD_KEYS) {
      expect(configProblems({ ip_id: "{custom.ip_id}", [key]: "x" })).toEqual([]);
    }
  });

  it("treats whitespace-only values as empty", () => {
    expect(configProblems({ ip_id: " ", status: "  " })).toEqual([
      "ip_id is not configured",
      NO_FIELD_PROBLEM,
    ]);
  });

  it("only asks for a field when the id is present", () => {
    expect(configProblems({ ip_id: "{custom.ip_id}" })).toEqual([NO_FIELD_PROBLEM]);
  });
});
