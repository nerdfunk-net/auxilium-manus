import { describe, expect, it } from "vitest";

import type { DatasetInfo } from "../types/report-query";
import {
  buildReportQuery,
  coerceFilterValue,
  DEFAULT_BUILDER_STATE,
  fieldChoices,
  metricFieldChoices,
  metricKey,
  normalizeBuilderState,
  outputKeys,
  operatorsForType,
  type BuilderState,
} from "./query-spec";

const DATASET: DatasetInfo = {
  name: "inventory",
  mode: "device",
  last_collected_at: null,
  fields: [
    { name: "serial", type: "string", null_share: 0, sample_values: [] },
    { name: "ports", type: "number", null_share: 0, sample_values: [] },
    { name: "stacked", type: "boolean", null_share: 0, sample_values: [] },
    { name: "misc", type: "mixed", null_share: 0, sample_values: [] },
  ],
};

function state(patch: Partial<BuilderState>): BuilderState {
  return { ...DEFAULT_BUILDER_STATE, sourceId: "report_data", dataset: "inventory", ...patch };
}

describe("operatorsForType", () => {
  it("offers numeric comparisons only for numbers", () => {
    expect(operatorsForType("number")).toContain("gt");
    expect(operatorsForType("string")).not.toContain("gt");
    expect(operatorsForType("boolean")).not.toContain("gt");
  });

  it("offers contains for text-like fields only", () => {
    for (const type of ["string", "mixed", "unknown"] as const) {
      expect(operatorsForType(type)).toContain("contains");
    }
    expect(operatorsForType("number")).not.toContain("contains");
  });

  it("always offers equality and null checks", () => {
    for (const type of ["string", "number", "boolean", "mixed", "unknown"] as const) {
      expect(operatorsForType(type)).toEqual(
        expect.arrayContaining(["eq", "ne", "in", "is_null", "not_null"]),
      );
    }
  });
});

describe("coerceFilterValue", () => {
  it("parses numbers and rejects non-numbers", () => {
    expect(coerceFilterValue("eq", "number", " 48 ")).toBe(48);
    expect(() => coerceFilterValue("eq", "number", "many")).toThrow(/number/);
  });

  it("parses booleans", () => {
    expect(coerceFilterValue("eq", "boolean", "true")).toBe(true);
    expect(coerceFilterValue("eq", "boolean", "false")).toBe(false);
    expect(() => coerceFilterValue("eq", "boolean", "yes")).toThrow(/true or false/);
  });

  it("keeps text as is and guesses scalars for mixed fields", () => {
    expect(coerceFilterValue("eq", "string", "dc1")).toBe("dc1");
    expect(coerceFilterValue("eq", "mixed", "10")).toBe(10);
    expect(coerceFilterValue("eq", "mixed", "true")).toBe(true);
    expect(coerceFilterValue("eq", "mixed", "abc")).toBe("abc");
  });

  it("splits a comma separated list for in", () => {
    expect(coerceFilterValue("in", "string", "a, b ,c")).toEqual(["a", "b", "c"]);
    expect(coerceFilterValue("in", "number", "1,2")).toEqual([1, 2]);
    expect(() => coerceFilterValue("in", "string", " , ")).toThrow(/at least one/);
  });

  it("needs a value except for null checks", () => {
    expect(() => coerceFilterValue("eq", "string", "")).toThrow(/value/);
    expect(coerceFilterValue("is_null", "string", "")).toBeUndefined();
  });
});

describe("fieldChoices / metricFieldChoices", () => {
  it("lists device_name first and every dataset field", () => {
    expect(fieldChoices(DATASET).map((f) => f.name)).toEqual([
      "device_name",
      "serial",
      "ports",
      "stacked",
      "misc",
    ]);
  });

  it("restricts numeric metrics to number fields", () => {
    expect(metricFieldChoices("sum", DATASET).map((f) => f.name)).toEqual(["ports"]);
    expect(metricFieldChoices("min", DATASET).map((f) => f.name)).toEqual([
      "device_name",
      "serial",
      "ports",
    ]);
    expect(metricFieldChoices("count_distinct", DATASET).map((f) => f.name)).toContain(
      "device_name",
    );
  });
});

describe("buildReportQuery", () => {
  it("builds a list query with all columns by default", () => {
    const result = buildReportQuery(state({}), DATASET);
    expect(result).toEqual({
      ok: true,
      query: {
        source: "report_data",
        dataset: "inventory",
        scope: { kind: "latest" },
        filters: [],
        group_by: [],
        metrics: [],
        select: [],
        order_by: [],
        limit: 500,
      },
    });
  });

  it("builds a grouped summary with a filter and ordering", () => {
    const result = buildReportQuery(
      state({
        mode: "summary",
        groupBy: ["serial"],
        metrics: [{ op: "count", field: "", alias: "devices" }],
        filters: [{ field: "ports", op: "gt", value: "24" }],
        orderKey: "devices",
        orderDirection: "desc",
        limit: "20",
      }),
      DATASET,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.query.group_by).toEqual(["serial"]);
    expect(result.query.metrics).toEqual([{ op: "count", alias: "devices" }]);
    expect(result.query.filters).toEqual([{ field: "ports", op: "gt", value: 24 }]);
    expect(result.query.order_by).toEqual([{ key: "devices", direction: "desc" }]);
    expect(result.query.limit).toBe(20);
  });

  it("only sends select columns in list mode", () => {
    const result = buildReportQuery(state({ select: ["serial"], groupBy: ["serial"] }), DATASET);
    expect(result.ok && result.query.select).toEqual(["serial"]);
    expect(result.ok && result.query.group_by).toEqual([]);
  });

  it("includes history bounds and bucket", () => {
    const result = buildReportQuery(
      state({
        scopeKind: "history",
        since: "2026-01-01T00:00",
        until: "",
        bucket: "day",
        mode: "summary",
        groupBy: ["time_bucket"],
        metrics: [{ op: "count", field: "", alias: "" }],
      }),
      DATASET,
    );
    expect(result.ok && result.query.scope).toEqual({
      kind: "history",
      since: new Date("2026-01-01T00:00").toISOString(),
      bucket: "day",
    });
  });

  it("builds device-level metrics without a field", () => {
    const result = buildReportQuery(
      state({
        mode: "summary",
        groupBy: ["device_name"],
        metrics: [{ op: "count_items", field: "", alias: "items" }],
      }),
      DATASET,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.query.metrics).toEqual([{ op: "count_items", alias: "items" }]);
  });

  it("offers no field choices for device-level metrics", () => {
    expect(metricFieldChoices("count_devices", DATASET)).toEqual([]);
    expect(metricFieldChoices("count_items", DATASET)).toEqual([]);
    expect(metricFieldChoices("count", DATASET).length).toBeGreaterThan(0);
  });

  it("collects readable errors instead of throwing", () => {
    const result = buildReportQuery(
      state({
        mode: "summary",
        groupBy: ["serial"],
        metrics: [],
        filters: [{ field: "ports", op: "eq", value: "many" }],
      }),
      DATASET,
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.join(" ")).toMatch(/metric/);
    expect(result.errors.join(" ")).toMatch(/ports/);
  });

  it("requires a dataset, a field for non-count metrics and a limit in range", () => {
    expect(buildReportQuery(state({ dataset: "" }), DATASET).ok).toBe(false);
    expect(
      buildReportQuery(
        state({ mode: "summary", metrics: [{ op: "sum", field: "", alias: "" }] }),
        DATASET,
      ).ok,
    ).toBe(false);
    expect(buildReportQuery(state({ limit: "0" }), DATASET).ok).toBe(false);
    expect(buildReportQuery(state({ limit: "5001" }), DATASET).ok).toBe(false);
    expect(buildReportQuery(state({ limit: "" }), DATASET).ok).toBe(false);
    expect(buildReportQuery(state({ limit: "12.5" }), DATASET).ok).toBe(false);
  });
});

describe("metricKey / outputKeys", () => {
  it("names metrics like the backend", () => {
    expect(metricKey({ op: "count", field: "", alias: "" })).toBe("count");
    expect(metricKey({ op: "sum", field: "ports", alias: "" })).toBe("sum_ports");
    expect(metricKey({ op: "count_devices", field: "", alias: "" })).toBe("count_devices");
    expect(metricKey({ op: "count_items", field: "", alias: "n" })).toBe("n");
    // A field left over from the previous operation must not leak into the column name.
    expect(metricKey({ op: "count_devices", field: "ports", alias: "" })).toBe("count_devices");
    expect(metricKey({ op: "sum", field: "ports", alias: "total" })).toBe("total");
  });

  it("lists the columns of a summary and of a list query", () => {
    const summary = state({
      mode: "summary",
      groupBy: ["serial"],
      metrics: [{ op: "count", field: "", alias: "devices" }],
    });
    expect(outputKeys(summary, DATASET)).toEqual(["serial", "devices"]);
    expect(outputKeys(state({ select: ["serial"] }), DATASET)).toEqual(["serial"]);
    expect(outputKeys(state({}), DATASET)[0]).toBe("device_name");
  });
});

describe("normalizeBuilderState", () => {
  it("drops an order key that is no longer an output column", () => {
    const summary = state({
      mode: "summary",
      groupBy: ["serial"],
      metrics: [{ op: "count", field: "", alias: "" }],
      orderKey: "count",
    });
    expect(normalizeBuilderState(summary, DATASET).orderKey).toBe("count");
    expect(normalizeBuilderState({ ...summary, mode: "rows" }, DATASET).orderKey).toBe("");
    expect(normalizeBuilderState(state({ select: ["ports"], orderKey: "serial" }), DATASET).orderKey).toBe("");
  });

  it("drops time_bucket grouping unless the scope is a bucketed history", () => {
    const base = state({
      mode: "summary",
      groupBy: ["time_bucket", "serial"],
      metrics: [{ op: "count", field: "", alias: "" }],
    });
    expect(normalizeBuilderState(base, DATASET).groupBy).toEqual(["serial"]);
    const bucketed = { ...base, scopeKind: "history" as const, bucket: "day" as const };
    expect(normalizeBuilderState(bucketed, DATASET).groupBy).toEqual(["time_bucket", "serial"]);
  });

  it("resets a metric field the operation no longer accepts", () => {
    const next = normalizeBuilderState(
      state({ mode: "summary", metrics: [{ op: "sum", field: "serial", alias: "" }] }),
      DATASET,
    );
    expect(next.metrics[0].field).toBe("");
  });

  it("resets an operator that is invalid for the filter's field type", () => {
    const next = normalizeBuilderState(
      state({ filters: [{ field: "serial", op: "gt", value: "24" }] }),
      DATASET,
    );
    expect(next.filters[0]).toEqual({ field: "serial", op: "eq", value: "" });
  });

  it("drops unknown selected columns and leaves valid state untouched", () => {
    const valid = state({ select: ["serial"], filters: [{ field: "ports", op: "gt", value: "1" }] });
    expect(normalizeBuilderState(valid, DATASET)).toEqual(valid);
    expect(normalizeBuilderState(state({ select: ["serial", "gone"] }), DATASET).select).toEqual(["serial"]);
  });
});

describe("metric column names", () => {
  const summary = (alias: string) =>
    buildReportQuery(
      state({ mode: "summary", metrics: [{ op: "count", field: "", alias }] }),
      DATASET,
    );

  it("accepts a lowercase name and rejects one the backend would refuse", () => {
    expect(summary("device_count").ok).toBe(true);
    for (const bad of ["Device Count", "1st", "device-count", "Devices"]) {
      const result = summary(bad);
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.errors[0]).toContain(`"${bad}"`);
    }
  });

  it("allows an empty name (an automatic one is used)", () => {
    expect(summary("  ").ok).toBe(true);
  });
});
