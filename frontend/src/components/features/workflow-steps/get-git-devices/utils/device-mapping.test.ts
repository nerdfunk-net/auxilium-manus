import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { NAUTOBOT_TARGETS } from "../constants/nautobot-targets";
import {
  DEFAULT_MAPPING,
  hasMappingErrors,
  mappingFromConfig,
  validateMapping,
} from "./device-mapping";

describe("validateMapping", () => {
  it("accepts the default mapping", () => {
    expect(hasMappingErrors(validateMapping(DEFAULT_MAPPING))).toBe(false);
  });

  it("accepts an empty mapping (backend falls back to the default)", () => {
    expect(hasMappingErrors(validateMapping([]))).toBe(false);
  });

  it("requires a name target", () => {
    const errors = validateMapping([{ source: "site", target: "location.name" }]);
    expect(errors.form).toMatch(/Device name/);
  });

  it("flags empty keys, unknown targets and duplicates per row", () => {
    const errors = validateMapping([
      { source: "n", target: "name" },
      { source: " ", target: "status.name" },
      { source: "x", target: "bogus" },
      { source: "y", target: "name" },
    ]);
    expect(Object.keys(errors.rows)).toEqual(["1", "2", "3"]);
  });
});

describe("mappingFromConfig", () => {
  it("returns [] for missing or malformed config", () => {
    expect(mappingFromConfig({})).toEqual([]);
    expect(mappingFromConfig({ device_mapping: {} })).toEqual([]);
  });

  it("keeps only well-formed rows", () => {
    expect(
      mappingFromConfig({
        device_mapping: [{ source: "a", target: "name" }, { source: 1 }, "x"],
      }),
    ).toEqual([{ source: "a", target: "name" }]);
  });
});

describe("target catalog", () => {
  it("matches NAUTOBOT_TARGETS in the backend", () => {
    const backend = readFileSync(
      resolve(process.cwd(), "../backend/services/git/device_mapping.py"),
      "utf-8",
    );
    const block = backend.match(/NAUTOBOT_TARGETS[^=]*=\s*\(([\s\S]*?)\n\)/)?.[1] ?? "";
    const backendTargets = [...block.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect(NAUTOBOT_TARGETS.map((t) => t.value)).toEqual(backendTargets);
  });
});
