import { describe, expect, it } from "vitest";

import {
  buildStoreForReportConfig,
  datasetNameError,
  fieldNameError,
  normalizeReportFields,
  normalizeReportMode,
  removeReportField,
  updateReportField,
} from "./config";

const BLANK = { aggregate: "" as const, where_field: "", where_equals: "" };

describe("buildStoreForReportConfig", () => {
  it("fills defaults for an empty config (mirrors backend get_config)", () => {
    expect(buildStoreForReportConfig({})).toEqual({
      dataset: "",
      mode: "device",
      items_path: "",
      fields: [],
    });
  });

  it("keeps a valid dataset, mode, items_path and fields", () => {
    const fields = [{ name: "intf", attribute_path: "intf", ...BLANK }];
    expect(
      buildStoreForReportConfig({
        dataset: "interfaces",
        mode: "items",
        items_path: "parsed.x",
        fields,
      }),
    ).toEqual({ dataset: "interfaces", mode: "items", items_path: "parsed.x", fields });
  });

  it("applies the patch last", () => {
    expect(buildStoreForReportConfig({ dataset: "a" }, { dataset: "b" }).dataset).toBe("b");
  });

  it("ignores a non-string dataset and an unknown mode", () => {
    const built = buildStoreForReportConfig({ dataset: 3, mode: "bogus" });
    expect(built.dataset).toBe("");
    expect(built.mode).toBe("device");
  });

  it("drops aggregation when switching to items mode", () => {
    const fields = [
      {
        name: "n",
        attribute_path: "p",
        aggregate: "count",
        where_field: "status",
        where_equals: "x",
      },
    ];
    const built = buildStoreForReportConfig({ mode: "device", fields }, { mode: "items" });
    expect(built.fields).toEqual([{ name: "n", attribute_path: "p", ...BLANK }]);
  });
});

describe("normalizeReportMode", () => {
  it("only accepts items, everything else is device", () => {
    expect(normalizeReportMode("items")).toBe("items");
    expect(normalizeReportMode(undefined)).toBe("device");
    expect(normalizeReportMode("x")).toBe("device");
  });
});

describe("normalizeReportFields", () => {
  it("returns an empty list for non-arrays", () => {
    expect(normalizeReportFields(undefined)).toEqual([]);
    expect(normalizeReportFields("x")).toEqual([]);
  });

  it("coerces malformed rows to blank strings and keeps blank rows", () => {
    expect(
      normalizeReportFields([null, { name: 1 }, { name: "a", attribute_path: "b.c" }]),
    ).toEqual([
      { name: "", attribute_path: "", ...BLANK },
      { name: "", attribute_path: "", ...BLANK },
      { name: "a", attribute_path: "b.c", ...BLANK },
    ]);
  });

  it("keeps count with its where in device mode", () => {
    const row = {
      name: "n",
      attribute_path: "p",
      aggregate: "count",
      where_field: "status",
      where_equals: "disabled",
    };
    expect(normalizeReportFields([row])).toEqual([row]);
  });

  it("clears a where when the field does not count", () => {
    expect(
      normalizeReportFields([
        { name: "n", attribute_path: "p", aggregate: "", where_field: "s", where_equals: "x" },
      ]),
    ).toEqual([{ name: "n", attribute_path: "p", ...BLANK }]);
  });

  it("ignores unknown aggregates", () => {
    expect(
      normalizeReportFields([{ name: "n", attribute_path: "p", aggregate: "sum" }])[0].aggregate,
    ).toBe("");
  });
});

describe("row helpers", () => {
  const rows = [
    { name: "a", attribute_path: "x", ...BLANK },
    { name: "b", attribute_path: "y", ...BLANK },
  ];

  it("updateReportField replaces one row without mutating the input", () => {
    const next = updateReportField(rows, 1, { attribute_path: "z" });
    expect(next).toEqual([rows[0], { ...rows[1], attribute_path: "z" }]);
    expect(rows[1].attribute_path).toBe("y");
  });

  it("removeReportField drops one row without mutating the input", () => {
    expect(removeReportField(rows, 0)).toEqual([rows[1]]);
    expect(rows).toHaveLength(2);
  });
});

describe("name validation (mirrors the backend grammar)", () => {
  it("accepts valid dataset names and ignores empty input", () => {
    for (const name of ["inventory", "inv-2", "device_types", "a", ""]) {
      expect(datasetNameError(name)).toBeNull();
    }
  });

  it("flags invalid dataset names", () => {
    for (const name of ["Inventory", "-x", "has space", "a.b", "x".repeat(101)]) {
      expect(datasetNameError(name)).not.toBeNull();
    }
  });

  it("accepts valid field names and ignores empty input", () => {
    for (const name of ["serial_number", "os2", "a", ""]) {
      expect(fieldNameError(name)).toBeNull();
    }
  });

  it("flags invalid field names", () => {
    for (const name of ["Serial", "2fast", "a-b", "a.b", "x".repeat(65)]) {
      expect(fieldNameError(name)).not.toBeNull();
    }
  });
});
