import { describe, expect, it } from "vitest";

import { configProblems, isValidMaskText, withNumberText } from "./config";

describe("add-ip-to-nautobot config helpers", () => {
  it("stores whole numbers as numbers and keeps other text as typed", () => {
    expect(withNumberText({}, "default_mask_length", " 26 ")).toEqual({
      default_mask_length: 26,
    });
    expect(withNumberText({}, "default_mask_length", "")).toEqual({ default_mask_length: "" });
    expect(withNumberText({}, "default_mask_length", "2x")).toEqual({
      default_mask_length: "2x",
    });
    expect(withNumberText({}, "default_mask_length", "-5")).toEqual({
      default_mask_length: "-5",
    });
  });

  it("does not mutate the previous config", () => {
    const previous = { ip_address: "1.1.1.1/24" };
    const next = withNumberText(previous, "default_mask_length", "24");
    expect(previous).toEqual({ ip_address: "1.1.1.1/24" });
    expect(next).toEqual({ ip_address: "1.1.1.1/24", default_mask_length: 24 });
  });

  it("accepts an empty mask or 1-128 only", () => {
    expect(isValidMaskText("")).toBe(true);
    expect(isValidMaskText("24")).toBe(true);
    expect(isValidMaskText("0")).toBe(false);
    expect(isValidMaskText("129")).toBe(false);
    expect(isValidMaskText("1.5")).toBe(false);
  });

  it("reports missing settings", () => {
    expect(configProblems({})).toEqual(["ip_address is not configured"]);
    expect(configProblems({ ip_address: "{custom.ip}" })).toEqual([]);
    expect(configProblems({ ip_address: "x", set_primary: true })).toEqual([
      "set_primary needs interface_name",
    ]);
    expect(configProblems({ ip_address: "x", set_primary: true, interface_name: "Vlan1" })).toEqual(
      [],
    );
  });
});
