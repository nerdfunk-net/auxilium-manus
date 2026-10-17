import { describe, expect, it } from "vitest";

import type { QueryResult, ReportQuerySpec } from "../types/report-query";
import { buildReportQuery, DEFAULT_BUILDER_STATE } from "./query-spec";
import {
  chartData,
  moveSection,
  newSectionId,
  queryToBuilderState,
  singleNumber,
} from "./report-sections";

const RESULT: QueryResult = {
  columns: [
    { key: "location", label: "location", type: "string" },
    { key: "devices", label: "devices", type: "number" },
    { key: "ports", label: "ports", type: "number" },
  ],
  rows: [
    ["dc1", 2, 48],
    ["dc2", 1, null],
  ],
  truncated: false,
};

describe("queryToBuilderState", () => {
  it("round-trips a summary query through the builder", () => {
    const query: ReportQuerySpec = {
      source: "report_data",
      dataset: "inventory",
      scope: { kind: "latest" },
      filters: [
        { field: "status", op: "eq", value: "up" },
        { field: "role", op: "in", value: ["a", "b"] },
        { field: "serial", op: "not_null" },
      ],
      group_by: ["location"],
      metrics: [{ op: "count", alias: "devices" }, { op: "sum", field: "ports" }],
      select: [],
      order_by: [{ key: "devices", direction: "desc" }],
      limit: 20,
    };
    const dataset = {
      name: "inventory",
      mode: "device" as const,
      last_collected_at: null,
      fields: [
        { name: "status", type: "string" as const, null_share: 0, sample_values: [] },
        { name: "role", type: "string" as const, null_share: 0, sample_values: [] },
        { name: "serial", type: "string" as const, null_share: 0, sample_values: [] },
        { name: "location", type: "string" as const, null_share: 0, sample_values: [] },
        { name: "ports", type: "number" as const, null_share: 0, sample_values: [] },
      ],
    };

    const built = buildReportQuery(queryToBuilderState(query), dataset);

    expect(built).toEqual({ ok: true, query });
  });

  it("uses list mode when there are no metrics", () => {
    const state = queryToBuilderState({
      source: "report_data",
      dataset: "d",
      scope: { kind: "history", bucket: "day" },
      filters: [],
      group_by: [],
      metrics: [],
      select: ["device_name"],
      order_by: [],
      limit: 500,
    });
    expect(state.mode).toBe("rows");
    expect(state.scopeKind).toBe("history");
    expect(state.bucket).toBe("day");
    expect(state.select).toEqual(["device_name"]);
    expect(state.limit).toBe("500");
    expect(DEFAULT_BUILDER_STATE.mode).toBe("rows");
  });
});

describe("chartData", () => {
  it("uses the first column as label and every numeric column as series", () => {
    const data = chartData(RESULT);
    expect(data.labelKey).toBe("location");
    expect(data.seriesKeys).toEqual(["devices", "ports"]);
    expect(data.points).toEqual([
      { location: "dc1", devices: 2, ports: 48 },
      { location: "dc2", devices: 1, ports: null },
    ]);
  });

  it("has no series when no column is numeric", () => {
    const data = chartData({
      columns: [{ key: "a", label: "a", type: "string" }],
      rows: [["x"]],
      truncated: false,
    });
    expect(data.seriesKeys).toEqual([]);
  });
});

describe("singleNumber", () => {
  it("takes the first numeric cell of the first row", () => {
    expect(singleNumber(RESULT)).toEqual({ label: "devices", value: 2 });
  });

  it("is null for an empty result", () => {
    expect(singleNumber({ ...RESULT, rows: [] })).toBeNull();
  });
});

describe("moveSection and newSectionId", () => {
  it("moves without mutating and ignores out-of-range moves", () => {
    const list = ["a", "b", "c"];
    expect(moveSection(list, 0, 1)).toEqual(["b", "a", "c"]);
    expect(moveSection(list, 0, -1)).toBe(list);
    expect(moveSection(list, 2, 1)).toBe(list);
    expect(list).toEqual(["a", "b", "c"]);
  });

  it("makes ids that are valid for the backend and unique", () => {
    const id = newSectionId(["section-1", "section-2"]);
    expect(id).toMatch(/^[a-z0-9][a-z0-9_-]{0,63}$/);
    expect(["section-1", "section-2"]).not.toContain(id);
  });
});
