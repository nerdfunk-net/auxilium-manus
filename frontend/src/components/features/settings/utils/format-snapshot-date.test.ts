import { describe, expect, it } from "vitest";

import { formatSnapshotDate, snapshotLabel } from "./format-snapshot-date";

describe("formatSnapshotDate", () => {
  it("handles missing and invalid input", () => {
    expect(formatSnapshotDate(null)).toBe("unknown date");
    expect(formatSnapshotDate("garbage")).toBe("unknown date");
  });

  it("formats a valid ISO timestamp", () => {
    expect(formatSnapshotDate("2026-11-17T09:30:00Z")).not.toBe("unknown date");
  });

  it("puts the date in braces behind the name", () => {
    expect(snapshotLabel("run-1", null)).toBe("run-1 (unknown date)");
  });
});
