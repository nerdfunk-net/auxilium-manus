import { describe, expect, it } from "vitest";

import { operatorRuleForField } from "./field-operators";

const values = (fieldName: string): string[] =>
  (operatorRuleForField(fieldName).options ?? []).map((option) => option.value);

describe("operatorRuleForField", () => {
  it("offers only equals / not equals for a location — never contains", () => {
    // "Location contains City" must not be possible (it would match "City A").
    expect(values("location")).toEqual(["equals", "not_equals"]);
  });

  it("keeps contains for device names and custom fields", () => {
    expect(values("name")).toEqual(["equals", "contains"]);
    expect(values("cf_site_code")).toEqual(["equals", "contains"]);
  });

  it("offers contains for nothing except device names and custom fields", () => {
    const fields = [
      "location",
      "role",
      "status",
      "tag",
      "device_type",
      "manufacturer",
      "platform",
      "has_primary",
      "ip_prefix",
      "primary_prefix",
    ];
    for (const field of fields) {
      expect(values(field), field).not.toContain("contains");
      expect(values(field), field).not.toContain("not_contains");
    }
  });

  it.each(["role", "manufacturer", "device_type", "status", "tag"])(
    "%s is equals / not equals",
    (field) => {
      expect(values(field)).toEqual(["equals", "not_equals"]);
      expect(operatorRuleForField(field).forcedOperator).toBeNull();
    },
  );

  it("restricts platform and has-primary to equals and forces it", () => {
    for (const field of ["platform", "has_primary"]) {
      expect(values(field)).toEqual(["equals"]);
      expect(operatorRuleForField(field).forcedOperator).toBe("equals");
    }
  });

  it("uses the prefix operators for the prefix fields and forces within_include", () => {
    expect(values("ip_prefix")).toEqual(["within_include", "within", "exact"]);
    expect(values("primary_prefix")).toEqual(["within_include"]);
    expect(operatorRuleForField("ip_prefix").forcedOperator).toBe("within_include");
    expect(operatorRuleForField("primary_prefix").forcedOperator).toBe("within_include");
  });

  it("falls back to the server-provided operators for unknown fields", () => {
    expect(operatorRuleForField("something_else")).toEqual({
      options: null,
      forcedOperator: null,
    });
    expect(operatorRuleForField("")).toEqual({ options: null, forcedOperator: null });
  });
});
