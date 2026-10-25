import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { NAUTOBOT_TARGETS } from "../constants/nautobot-targets";
import { IGNORE_TARGET, PRIMARY_FLAG_TARGET, isKnownTarget } from "../constants/nautobot-targets";
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
  it("maps namespace columns to the interface IP namespace", () => {
    for (const key of ["namespace", "interface_namespace", "interface_ip_namespace"]) {
      expect(suggestTarget(key)).toBe("interfaces.ip_addresses.parent.namespace.name");
    }
  });

  it("ignores a namespace column when the file has no interface IP address column", () => {
    const rows = mappingFromKeys([], ["name", "namespace"]);
    expect(rows.find((r) => r.source === "namespace")?.target).toBe(IGNORE_TARGET);
    expect(hasMappingErrors(validateMapping(rows))).toBe(false);
  });

  it("pre-fills the whole interface CSV from its header", () => {
    const rows = mappingFromKeys(
      [],
      ["name", "interface_name", "interface_address", "is_primary", "namespace"],
    );
    expect(rows.map((r) => r.target)).toEqual([
      "name",
      "interfaces.name",
      "interfaces.ip_addresses.address",
      PRIMARY_FLAG_TARGET,
      "interfaces.ip_addresses.parent.namespace.name",
    ]);
    expect(hasMappingErrors(validateMapping(rows))).toBe(false);
  });

  it("maps interface_address to the interface IP address", () => {
    expect(suggestTarget("interface_address")).toBe("interfaces.ip_addresses.address");
  });

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
    expect(suggestTarget("something_else")).toBe(IGNORE_TARGET);
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

describe("namespace and custom value targets", () => {
  const name = { source: "name", target: "name" };

  it("accepts namespace targets and custom values", () => {
    const errors = validateMapping([
      name,
      { source: "primary_ip4", target: "primary_ip4.address" },
      { source: "ns", target: "primary_ip4.parent.namespace.name" },
      { source: "ns2", target: "custom.namespace" },
    ]);
    expect(hasMappingErrors(errors)).toBe(false);
  });

  it("asks for a name when the custom value name is empty", () => {
    const errors = validateMapping([name, { source: "x", target: "custom." }]);
    expect(errors.rows[1]).toBe("Enter a custom value name");
  });

  it("rejects invalid custom value names", () => {
    const errors = validateMapping([name, { source: "x", target: "custom.a b" }]);
    expect(errors.rows[1]).toBe("Custom value names may only contain letters, digits and underscores");
  });

  it("requires an interface IP address for an interface IP namespace", () => {
    const errors = validateMapping([
      name,
      { source: "interface", target: "interfaces.name" },
      { source: "ns", target: "interfaces.ip_addresses.parent.namespace.name" },
    ]);
    expect(errors.form).toContain("Interface IP address");
  });

  it("requires a primary IPv4 address for a primary IPv4 namespace", () => {
    const errors = validateMapping([
      name,
      { source: "ns", target: "primary_ip4.parent.namespace.name" },
    ]);
    expect(errors.form).toContain("Primary IPv4 address");
  });

  it("does not confuse custom values with custom fields", () => {
    expect(isKnownTarget("custom.ns")).toBe(true);
    expect(isKnownTarget("custom_fields.ns")).toBe(true);
    expect(isKnownTarget("customs.ns")).toBe(false);
  });
});

describe("primary flag target", () => {
  const base = [
    { source: "name", target: "name" },
    { source: "interface_name", target: "interfaces.name" },
    { source: "interface_address", target: "interfaces.ip_addresses.address" },
  ];

  it("is a known target and is suggested for is_primary", () => {
    expect(isKnownTarget(PRIMARY_FLAG_TARGET)).toBe(true);
    expect(suggestTarget("is_primary")).toBe(PRIMARY_FLAG_TARGET);
  });

  it("accepts the flag next to an interface IP column", () => {
    const rules = [...base, { source: "is_primary", target: PRIMARY_FLAG_TARGET }];
    expect(hasMappingErrors(validateMapping(rules))).toBe(false);
  });

  it("may only be mapped once", () => {
    const rules = [
      ...base,
      { source: "a", target: PRIMARY_FLAG_TARGET },
      { source: "b", target: PRIMARY_FLAG_TARGET },
    ];
    expect(validateMapping(rules).rows[4]).toMatch(/only be mapped once/);
  });

  it("needs an interface IP address column", () => {
    const rules = [
      { source: "name", target: "name" },
      { source: "is_primary", target: PRIMARY_FLAG_TARGET },
    ];
    expect(validateMapping(rules).form).toMatch(/Interface IP address/);
  });

  it("cannot be combined with a primary IPv4 target", () => {
    const rules = [
      ...base,
      { source: "is_primary", target: PRIMARY_FLAG_TARGET },
      { source: "mgmt", target: "primary_ip4.address" },
    ];
    expect(validateMapping(rules).form).toMatch(/Primary IPv4/);
  });

  it("is only suggested once when two keys would claim it", () => {
    const rows = mappingFromKeys([], ["is_primary", "primary"]);
    expect(rows.filter((r) => r.target === PRIMARY_FLAG_TARGET)).toHaveLength(1);
  });
});
