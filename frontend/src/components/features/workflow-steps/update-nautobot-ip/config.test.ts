import { describe, expect, it } from "vitest";

import {
  INTERFACE_IP_ID_PROBLEM,
  IP_VERSION_ANY,
  NO_FIELD_PROBLEM,
  UPDATE_FIELD_KEYS,
  configProblems,
  interfaceModeEnabledPatch,
  ipVersionFromConfig,
  isFromInterfaces,
} from "./config";

describe("update-nautobot-ip config helpers", () => {
  it("reports a missing ip_id and a missing field", () => {
    expect(configProblems({})).toEqual([
      "ip_id is not configured",
      NO_FIELD_PROBLEM,
    ]);
  });

  it("is complete with an id and any single field", () => {
    for (const key of UPDATE_FIELD_KEYS) {
      expect(configProblems({ ip_id: "{custom.ip_id}", [key]: "x" })).toEqual(
        [],
      );
    }
  });

  it("treats whitespace-only values as empty", () => {
    expect(configProblems({ ip_id: " ", status: "  " })).toEqual([
      "ip_id is not configured",
      NO_FIELD_PROBLEM,
    ]);
  });

  it("only asks for a field when the id is present", () => {
    expect(configProblems({ ip_id: "{custom.ip_id}" })).toEqual([
      NO_FIELD_PROBLEM,
    ]);
  });
});

describe("IP addresses from interfaces mode", () => {
  it("needs no ip_id but still one field", () => {
    expect(configProblems({ ips_from_interfaces: true })).toEqual([
      NO_FIELD_PROBLEM,
    ]);
    expect(
      configProblems({ ips_from_interfaces: true, status: "Active" }),
    ).toEqual([]);
    expect(
      configProblems({
        ips_from_interfaces: "true",
        description: "{interface.name}",
      }),
    ).toEqual([]);
  });

  it("warns about an ip_id the mode refuses", () => {
    expect(
      configProblems({
        ips_from_interfaces: true,
        ip_id: "{custom.ip_id}",
        status: "Active",
      }),
    ).toEqual([INTERFACE_IP_ID_PROBLEM]);
  });

  it("recognises the stored flag as a boolean or a string", () => {
    expect(isFromInterfaces({ ips_from_interfaces: true })).toBe(true);
    expect(isFromInterfaces({ ips_from_interfaces: " TRUE " })).toBe(true);
    expect(isFromInterfaces({ ips_from_interfaces: false })).toBe(false);
    expect(isFromInterfaces({})).toBe(false);
  });

  it("clears only the ip_id when the mode is switched on and keeps the values", () => {
    const patch = interfaceModeEnabledPatch();
    expect(patch).toEqual({ ips_from_interfaces: true, ip_id: "" });
    expect(configProblems({ status: "Active", ...patch })).toEqual([]);
  });

  it("shows any for an empty or unknown IP version", () => {
    expect(ipVersionFromConfig({})).toBe(IP_VERSION_ANY);
    expect(ipVersionFromConfig({ ip_version: "7" })).toBe(IP_VERSION_ANY);
    expect(ipVersionFromConfig({ ip_version: "6" })).toBe("6");
    expect(ipVersionFromConfig({ ip_version: 4 })).toBe("4");
  });
});
