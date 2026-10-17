import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { NAUTOBOT_TARGETS } from "../constants/nautobot-targets";
import { IGNORE_TARGET } from "../constants/nautobot-targets";
import {
  DEFAULT_MAPPING,
  hasMappingErrors,
  mappingFromConfig,
  mappingFromKeys,
  suggestTarget,
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

describe("custom fields and interfaces", () => {
  const name = { source: "name", target: "name" };

  it("accepts custom field targets with simple names", () => {
    const errors = validateMapping([name, { source: "cf_x", target: "custom_fields.snmp_credentials" }]);
    expect(hasMappingErrors(errors)).toBe(false);
  });

  it("asks for a name when the custom field name is empty", () => {
    const errors = validateMapping([name, { source: "x", target: "custom_fields." }]);
    expect(errors.rows[1]).toBe("Enter a custom field name");
  });

  it("rejects invalid custom field names", () => {
    const errors = validateMapping([name, { source: "x", target: "custom_fields.a b" }]);
    expect(errors.rows[1]).toBeDefined();
  });

  it("requires an interface name when other interface attributes are mapped", () => {
    const errors = validateMapping([
      name,
      { source: "ip", target: "interfaces.ip_addresses.address" },
    ]);
    expect(errors.form).toMatch(/Interface name/);
    const ok = validateMapping([
      name,
      { source: "ip", target: "interfaces.ip_addresses.address" },
      { source: "i", target: "interfaces.name" },
    ]);
    expect(hasMappingErrors(ok)).toBe(false);
  });
});

describe("ignore target", () => {
  it("may be used for any number of columns", () => {
    const errors = validateMapping([
      { source: "name", target: "name" },
      { source: "a", target: IGNORE_TARGET },
      { source: "b", target: IGNORE_TARGET },
    ]);
    expect(hasMappingErrors(errors)).toBe(false);
  });

  it("matches IGNORE_TARGET in the backend", () => {
    const backend = readFileSync(
      resolve(process.cwd(), "../backend/services/git/device_mapping.py"),
      "utf-8",
    );
    expect(backend).toContain(`IGNORE_TARGET = "${IGNORE_TARGET}"`);
  });
});

describe("suggestTarget", () => {
  it("recognises common column names, case-insensitively", () => {
    expect(suggestTarget("ip_address")).toBe("primary_ip4.address");
    expect(suggestTarget("Role")).toBe("role.name");
    expect(suggestTarget("interface_ip_address")).toBe("interfaces.ip_addresses.address");
  });

  it("maps cf_ columns to custom fields", () => {
    expect(suggestTarget("cf_snmp_credentials")).toBe("custom_fields.snmp_credentials");
    expect(suggestTarget("cf_")).toBe(IGNORE_TARGET);
  });

  it("falls back to ignore for unknown columns", () => {
    expect(suggestTarget("namespace")).toBe(IGNORE_TARGET);
  });
});

describe("mappingFromKeys", () => {
  const keys = [
    "name",
    "ip_address",
    "role",
    "status",
    "location",
    "namespace",
    "cf_net",
    "interface_name",
  ];

  it("adds one row per key, replacing the untouched default mapping", () => {
    const rules = mappingFromKeys(DEFAULT_MAPPING, keys);
    expect(rules.map((r) => r.source)).toEqual(keys);
    expect(rules.find((r) => r.source === "namespace")?.target).toBe(IGNORE_TARGET);
    expect(rules.find((r) => r.source === "cf_net")?.target).toBe("custom_fields.net");
    expect(hasMappingErrors(validateMapping(rules))).toBe(false);
  });

  it("keeps existing rows and only adds missing keys", () => {
    const existing = [{ source: "name", target: "name" }, { source: "site", target: "location.name" }];
    const rules = mappingFromKeys(existing, ["name", "site", "location", "role"]);
    expect(rules.slice(0, 2)).toEqual(existing);
    // "location" would also suggest location.name, which is taken → ignored.
    expect(rules.find((r) => r.source === "location")?.target).toBe(IGNORE_TARGET);
    expect(rules.find((r) => r.source === "role")?.target).toBe("role.name");
  });

  it("skips nested dot-path keys", () => {
    expect(mappingFromKeys([], ["loc", "loc.site", "name"]).map((r) => r.source)).toEqual([
      "loc",
      "name",
    ]);
  });
});
