import { describe, expect, it } from "vitest";

import { DEFAULT_PARSED_LIST_CONFIG } from "./types";
import {
  interfaceSourceProblem,
  interfacesSourceFromConfig,
  parseParsedListConfig,
  parsedListForSave,
  parsedListProblem,
} from "./update-device-config";

const BASE = {
  source_path: "parsed.a.rows",
  field_map: { name: "interface" },
  fixed_values: {},
  new_interface_type: { mode: "none", value: "" },
} as const;

describe("interfacesSourceFromConfig", () => {
  it("knows the three sources and falls back to manual", () => {
    expect(interfacesSourceFromConfig({ interfaces_source: "parsed_list" })).toBe("parsed_list");
    expect(interfacesSourceFromConfig({ interfaces_source: "nautobot_origin" })).toBe(
      "nautobot_origin",
    );
    expect(interfacesSourceFromConfig({ interfaces_source: "bogus" })).toBe("manual");
    expect(interfacesSourceFromConfig({})).toBe("manual");
  });
});

describe("parseParsedListConfig", () => {
  it("returns the defaults for missing or malformed input", () => {
    expect(parseParsedListConfig(undefined)).toBe(DEFAULT_PARSED_LIST_CONFIG);
    expect(parseParsedListConfig([])).toBe(DEFAULT_PARSED_LIST_CONFIG);
    expect(parseParsedListConfig("x")).toBe(DEFAULT_PARSED_LIST_CONFIG);
  });

  it("keeps known fields and drops unknown keys and non-string values", () => {
    const parsed = parseParsedListConfig({
      source_path: "parsed.a.rows",
      field_map: { name: "interface", mac_address: "mac", colour: "x", mtu: 5 },
      fixed_values: { type: "1000base-t" },
    });
    expect(parsed).toEqual({
      source_path: "parsed.a.rows",
      field_map: { name: "interface", mac_address: "mac" },
      fixed_values: { type: "1000base-t" },
      new_interface_type: { mode: "none", value: "" },
    });
  });
});

describe("parsedListForSave", () => {
  it("trims values and drops blank entries", () => {
    expect(
      parsedListForSave({
        source_path: "  parsed.a.rows ",
        field_map: { name: " interface ", mtu: "  ", mac_address: "mac" },
        fixed_values: { type: "", mode: "access" },
        new_interface_type: { mode: "none", value: "" },
      }),
    ).toEqual({
      source_path: "parsed.a.rows",
      field_map: { name: "interface", mac_address: "mac" },
      fixed_values: { mode: "access" },
      new_interface_type: { mode: "none", value: "" },
    });
  });
});

describe("parsedListProblem", () => {
  it("asks for the list, then for the name column", () => {
    expect(parsedListProblem({ ...BASE, source_path: "", field_map: {} })).toMatch(
      /source path/,
    );
    expect(
      parsedListProblem({ ...BASE, source_path: "parsed.a", field_map: {} }),
    ).toMatch(/name/);
    expect(
      parsedListProblem({ ...BASE, source_path: "parsed.a" }),
    ).toBeNull();
  });
});

describe("new_interface_type", () => {
  it("defaults to none when absent or malformed", () => {
    expect(parseParsedListConfig({ source_path: "p" }).new_interface_type).toEqual({
      mode: "none",
      value: "",
    });
    expect(
      parseParsedListConfig({ source_path: "p", new_interface_type: "infer" }).new_interface_type,
    ).toEqual({ mode: "none", value: "" });
    expect(
      parseParsedListConfig({ source_path: "p", new_interface_type: { mode: "bogus" } })
        .new_interface_type.mode,
    ).toBe("none");
  });

  it("round-trips infer and fixed", () => {
    expect(
      parseParsedListConfig({ source_path: "p", new_interface_type: { mode: "infer" } })
        .new_interface_type,
    ).toEqual({ mode: "infer", value: "" });
    expect(
      parseParsedListConfig({
        source_path: "p",
        new_interface_type: { mode: "fixed", value: "virtual" },
      }).new_interface_type,
    ).toEqual({ mode: "fixed", value: "virtual" });
  });

  it("drops the value unless the mode is fixed when saving", () => {
    const save = (mode: "none" | "infer" | "fixed", value: string) =>
      parsedListForSave({ ...BASE, new_interface_type: { mode, value } }).new_interface_type;
    expect(save("infer", "virtual")).toEqual({ mode: "infer", value: "" });
    expect(save("none", "virtual")).toEqual({ mode: "none", value: "" });
    expect(save("fixed", "  virtual ")).toEqual({ mode: "fixed", value: "virtual" });
  });

  it("blocks saving a fixed type without a value", () => {
    const problem = (mode: "none" | "infer" | "fixed", value: string) =>
      parsedListProblem({ ...BASE, new_interface_type: { mode, value } });
    expect(problem("fixed", " ")).toMatch(/type/i);
    expect(problem("fixed", "virtual")).toBeNull();
    expect(problem("infer", "")).toBeNull();
  });
});

describe("interfaceSourceProblem", () => {
  const ok = { sync_interfaces: false };

  it("accepts the supported combinations", () => {
    expect(interfaceSourceProblem("manual", "explicit", ok)).toBeNull();
    expect(interfaceSourceProblem("manual", "explicit", { sync_interfaces: true })).toBeNull();
    expect(interfaceSourceProblem("parsed_list", "from_context", ok)).toBeNull();
    expect(interfaceSourceProblem("nautobot_origin", "from_context", ok)).toBeNull();
    expect(
      interfaceSourceProblem("nautobot_origin", "from_context", { sync_interfaces: true }),
    ).toBeNull();
  });

  it("refuses a source that needs devices from upstream together with an explicit device", () => {
    expect(interfaceSourceProblem("parsed_list", "explicit", ok)).toMatch(/explicit/);
    expect(interfaceSourceProblem("nautobot_origin", "explicit", ok)).toMatch(/explicit/);
  });

  it("refuses sync_interfaces with a parsed list", () => {
    expect(
      interfaceSourceProblem("parsed_list", "from_context", { sync_interfaces: true }),
    ).toMatch(/sync_interfaces/);
  });
});
