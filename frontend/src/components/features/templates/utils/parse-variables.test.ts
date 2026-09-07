import { describe, expect, it } from "vitest";

import {
  flattenVariablesRecord,
  validateDestinationPath,
} from "./parse-variables";

describe("flattenVariablesRecord", () => {
  it("keeps a top-level string value verbatim", () => {
    expect(flattenVariablesRecord({ hostname: "r1" })).toEqual([
      { name: "hostname", value: "r1" },
    ]);
  });

  it("stringifies numbers, booleans and null", () => {
    expect(flattenVariablesRecord({ n: 10, ok: true, none: null })).toEqual([
      { name: "n", value: "10" },
      { name: "ok", value: "true" },
      { name: "none", value: "null" },
    ]);
  });

  it("pretty-prints nested objects and arrays as JSON", () => {
    const [entry] = flattenVariablesRecord({ meta: { site: "DC1" } });
    expect(entry.name).toBe("meta");
    expect(entry.value).toBe(JSON.stringify({ site: "DC1" }, null, 2));

    const [list] = flattenVariablesRecord({ dns: ["1.1.1.1", "8.8.8.8"] });
    expect(list.value).toBe(JSON.stringify(["1.1.1.1", "8.8.8.8"], null, 2));
  });

  it("trims key names", () => {
    expect(flattenVariablesRecord({ "  x  ": 1 })[0].name).toBe("x");
  });

  it("returns [] for an empty object", () => {
    expect(flattenVariablesRecord({})).toEqual([]);
  });

  it("throws for a non-mapping top level", () => {
    expect(() => flattenVariablesRecord([1, 2])).toThrow(/top-level mapping/);
    expect(() => flattenVariablesRecord("scalar")).toThrow(/top-level mapping/);
    expect(() => flattenVariablesRecord(null)).toThrow(/top-level mapping/);
  });

  it("prefixes every key with the destination path", () => {
    expect(
      flattenVariablesRecord({ snmp1: { username: "noc" }, region: "emea" }, "data"),
    ).toEqual([
      { name: "data.snmp1", value: JSON.stringify({ username: "noc" }, null, 2) },
      { name: "data.region", value: "emea" },
    ]);
  });

  it("supports a multi-segment destination path", () => {
    expect(flattenVariablesRecord({ snmp1: 1 }, "data.snmp")).toEqual([
      { name: "data.snmp.snmp1", value: "1" },
    ]);
  });

  it("rejects an invalid destination path", () => {
    expect(() => flattenVariablesRecord({ x: 1 }, "")).toThrow(/required/);
    expect(() => flattenVariablesRecord({ x: 1 }, "device.name")).toThrow(/device/);
    expect(() => flattenVariablesRecord({ x: 1 }, "parsed")).toThrow(/reserved/);
    expect(() => flattenVariablesRecord({ x: 1 }, "data..snmp")).toThrow(/empty/);
  });
});

describe("validateDestinationPath", () => {
  it("returns the trimmed path", () => {
    expect(validateDestinationPath("  data.snmp  ")).toBe("data.snmp");
  });

  it("rejects empty, device.*, reserved roots and empty segments", () => {
    expect(() => validateDestinationPath("")).toThrow(/required/);
    expect(() => validateDestinationPath("   ")).toThrow(/required/);
    expect(() => validateDestinationPath("device.hostname")).toThrow(/device/);
    expect(() => validateDestinationPath("run_input")).toThrow(/reserved/);
    expect(() => validateDestinationPath("hostname")).toThrow(/reserved/);
    expect(() => validateDestinationPath("data.")).toThrow(/empty/);
  });
});
