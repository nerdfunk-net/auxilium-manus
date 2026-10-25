import { describe, expect, it } from "vitest";

import { DEVICE_ID_MISSING_PROBLEM, configProblems, removeIpAddressesFromConfig } from "./config";

describe("remove-from-nautobot config helpers", () => {
  it("reports a missing or blank device_id", () => {
    expect(configProblems({})).toEqual([DEVICE_ID_MISSING_PROBLEM]);
    expect(configProblems({ device_id: "  " })).toEqual([DEVICE_ID_MISSING_PROBLEM]);
  });

  it("is complete with a device_id", () => {
    expect(configProblems({ device_id: "{device.id}" })).toEqual([]);
  });

  it("reads the flag as a boolean, defaulting to off", () => {
    expect(removeIpAddressesFromConfig({})).toBe(false);
    expect(removeIpAddressesFromConfig({ remove_ip_addresses: true })).toBe(true);
    expect(removeIpAddressesFromConfig({ remove_ip_addresses: "true" })).toBe(true);
    expect(removeIpAddressesFromConfig({ remove_ip_addresses: "false" })).toBe(false);
  });
});
