import { describe, expect, it } from "vitest";

import {
  buildDiscoverNetworkConfig,
  clampConcurrency,
  clampMaxDepth,
  clampMaxDevices,
  configIssues,
  parsePrefixText,
  validatePrefix,
} from "./config";

describe("parsePrefixText", () => {
  it("splits on lines and commas, trims, drops blanks and duplicates", () => {
    expect(parsePrefixText(" 10.1.0.0/16\n\n192.168.5.0/24, 10.1.0.0/16 \n")).toEqual([
      "10.1.0.0/16",
      "192.168.5.0/24",
    ]);
    expect(parsePrefixText("")).toEqual([]);
  });
});

describe("validatePrefix", () => {
  it("accepts IPv4 CIDR prefixes of /8 or more specific", () => {
    for (const ok of ["10.1.0.0/16", "192.168.5.0/24", "10.0.0.0/8", "10.1.2.3/32"]) {
      expect(validatePrefix(ok)).toBeNull();
    }
  });

  it.each([
    ["10.1.0.0", "CIDR"],
    ["10.1.0.5/24", "host bits"],
    ["10.1.0.0/33", "CIDR"],
    ["300.1.0.0/16", "CIDR"],
    ["not-a-prefix", "CIDR"],
    ["2001:db8::/32", "IPv4"],
    ["0.0.0.0/0", "broad"],
    ["10.0.0.0/7", "broad"],
    ["127.0.0.0/8", "never"],
    ["169.254.0.0/16", "never"],
    ["224.0.0.0/4", "broad"],
    ["240.0.0.0/8", "never"],
  ])("rejects %s", (value, fragment) => {
    expect(validatePrefix(value)).toContain(fragment);
  });
});

describe("clamps", () => {
  it("keep the numbers inside the backend ranges", () => {
    expect(clampMaxDevices("0")).toBe(1);
    expect(clampMaxDevices("9999")).toBe(500);
    expect(clampMaxDevices("x")).toBe(50);
    expect(clampMaxDepth("0")).toBe(1);
    expect(clampMaxDepth("99")).toBe(20);
    expect(clampMaxDepth("")).toBe(5);
    expect(clampConcurrency("0")).toBe(1);
    expect(clampConcurrency("99")).toBe(20);
    expect(clampConcurrency("7")).toBe(7);
  });
});

describe("buildDiscoverNetworkConfig", () => {
  it("defaults to not following, infrastructure only and the documented limits", () => {
    expect(buildDiscoverNetworkConfig({})).toMatchObject({
      follow_neighbors: false,
      permitted_prefixes: [],
      follow_only_infrastructure: true,
      max_devices: 50,
      max_depth: 5,
      concurrency: 5,
    });
  });

  it("keeps the prefixes when following is switched off", () => {
    const built = buildDiscoverNetworkConfig(
      { follow_neighbors: true, permitted_prefixes: ["10.1.0.0/16"] },
      { follow_neighbors: false },
    );
    expect(built.follow_neighbors).toBe(false);
    expect(built.permitted_prefixes).toEqual(["10.1.0.0/16"]);
  });

  it("merges a patch and does not mutate the input", () => {
    const input = { follow_neighbors: false, permitted_prefixes: ["10.1.0.0/16"] };
    const built = buildDiscoverNetworkConfig(input, { permitted_prefixes: ["10.2.0.0/16"] });
    expect(built.permitted_prefixes).toEqual(["10.2.0.0/16"]);
    expect(input.permitted_prefixes).toEqual(["10.1.0.0/16"]);
  });

  it("repairs values of the wrong type", () => {
    const built = buildDiscoverNetworkConfig({
      follow_neighbors: "yes",
      permitted_prefixes: "10.1.0.0/16",
      max_devices: "many",
    });
    expect(built.follow_neighbors).toBe(false);
    expect(built.permitted_prefixes).toEqual([]);
    expect(built.max_devices).toBe(50);
  });
});

describe("configIssues", () => {
  it("asks for a prefix when following without any", () => {
    expect(configIssues({ follow_neighbors: true, permitted_prefixes: [] })).toEqual([
      "Add at least one permitted prefix to log into discovered devices.",
    ]);
  });

  it("reports each invalid prefix, also when not following", () => {
    expect(
      configIssues({ follow_neighbors: false, permitted_prefixes: ["10.1.0.0/16", "bad"] }),
    ).toEqual([expect.stringContaining("bad")]);
  });

  it("has no issues for a valid configuration", () => {
    expect(
      configIssues({ follow_neighbors: true, permitted_prefixes: ["10.1.0.0/16"] }),
    ).toEqual([]);
    expect(configIssues({})).toEqual([]);
  });
});
