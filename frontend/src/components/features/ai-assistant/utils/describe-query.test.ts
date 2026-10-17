import { describe, expect, it } from "vitest";

import type { ReportQuerySpec } from "@/components/features/reports/types/report-query";

import { describeQuery } from "./describe-query";

const BASE: ReportQuerySpec = {
  source: "report_data",
  dataset: "inventory",
  scope: { kind: "latest" },
  filters: [],
  group_by: [],
  metrics: [],
  select: [],
  order_by: [],
  limit: 500,
};

describe("describeQuery", () => {
  it("describes a plain list", () => {
    expect(describeQuery(BASE)).toEqual([
      "Dataset: inventory",
      "Scope: latest collection per device",
      "Shows all columns",
      "Limit: 500",
    ]);
  });

  it("describes a summary with filters, grouping, metrics and order", () => {
    const lines = describeQuery({
      ...BASE,
      scope: { kind: "history", since: "2026-01-01T00:00:00Z", bucket: "day" },
      filters: [
        { field: "status", op: "eq", value: "up" },
        { field: "role", op: "in", value: ["a", "b"] },
        { field: "serial", op: "not_null" },
      ],
      group_by: ["location"],
      metrics: [{ op: "count", alias: "devices" }, { op: "sum", field: "ports" }],
      order_by: [{ key: "devices", direction: "desc" }],
      limit: 20,
    });

    expect(lines).toContain("Scope: history from 2026-01-01T00:00:00Z, per day");
    expect(lines).toContain("Filter: status equals up");
    expect(lines).toContain("Filter: role is one of a, b");
    expect(lines).toContain("Filter: serial is not empty");
    expect(lines).toContain("Group by: location");
    expect(lines).toContain("Metric: Count rows as devices");
    expect(lines).toContain("Metric: Sum of ports");
    expect(lines).toContain("Order by: devices (descending)");
    expect(lines).not.toContain("Shows all columns");
  });

  it("lists the selected columns", () => {
    expect(describeQuery({ ...BASE, select: ["device_name", "serial"] })).toContain(
      "Columns: device_name, serial",
    );
  });
});
