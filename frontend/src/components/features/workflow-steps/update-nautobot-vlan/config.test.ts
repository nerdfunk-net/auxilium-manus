import { describe, expect, it } from "vitest";

import {
  INTERFACE_CONFLICT_PROBLEM,
  interfaceModeEnabledPatch,
  NO_FIELD_PROBLEM,
  NO_VLAN_PROBLEM,
  UPDATE_FIELD_KEYS,
  configProblems,
} from "./config";
import { BAD_MODE_PROBLEM, locationsModeFromConfig } from "../shared/nautobot-locations";

describe("update-nautobot-vlan config helpers", () => {
  it("reports a missing VLAN selector and a missing field", () => {
    expect(configProblems({})).toEqual([NO_VLAN_PROBLEM, NO_FIELD_PROBLEM]);
  });

  it("accepts vlan_id or vid as the selector", () => {
    expect(configProblems({ vlan_id: "{custom.v}", status: "Active" })).toEqual(
      [],
    );
    expect(configProblems({ vid: "100", status: "Active" })).toEqual([]);
  });

  it("is complete with any single field", () => {
    for (const key of UPDATE_FIELD_KEYS) {
      expect(configProblems({ vid: "100", [key]: "x" })).toEqual([]);
    }
  });

  it("treats whitespace-only values as empty", () => {
    expect(configProblems({ vid: " ", status: "  " })).toEqual([
      NO_VLAN_PROBLEM,
      NO_FIELD_PROBLEM,
    ]);
  });

  it("shows replace when no mode is stored", () => {
    expect(locationsModeFromConfig({})).toBe("replace");
    expect(locationsModeFromConfig({ locations_mode: "add" })).toBe("add");
    expect(configProblems({ vid: "1", status: "x" })).toEqual([]);
  });

  it("does not show an unknown stored mode as replace", () => {
    const config = { vid: "1", status: "x", locations_mode: "merge" };
    expect(locationsModeFromConfig(config)).toBe("");
    expect(configProblems(config)).toEqual([BAD_MODE_PROBLEM]);
  });
});

describe("VLANs from interfaces mode", () => {
  it("needs no VLAN selector and no field", () => {
    expect(configProblems({ vlans_from_interfaces: true })).toEqual([]);
    expect(
      configProblems({ vlans_from_interfaces: "true", dry_run: true }),
    ).toEqual([]);
  });

  it("warns about a field the mode refuses", () => {
    expect(
      configProblems({ vlans_from_interfaces: true, status: "Active" }),
    ).toEqual([INTERFACE_CONFLICT_PROBLEM]);
  });

  it("clears the refused keys when the mode is switched on", () => {
    const patch = interfaceModeEnabledPatch();
    expect(patch).toMatchObject({
      vlans_from_interfaces: true,
      locations_mode: "add",
      vid: "",
    });
    expect(configProblems({ vid: "1", ...patch })).toEqual([]);
  });
});
