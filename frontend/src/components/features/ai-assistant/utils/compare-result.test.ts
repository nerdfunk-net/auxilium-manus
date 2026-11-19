import { describe, expect, it } from "vitest";

import {
  DEFAULT_INLINE_LIMIT,
  SAMPLE_ROWS,
  compareCsv,
  compareFileName,
  fieldLabel,
  parseCompareProposal,
  parseCompareResponse,
  splitSides,
  usedFileColumns,
  visibleRows,
} from "./compare-result";

const RESPONSE = {
  repository: "Gitea CSV",
  file: "data/compare.csv",
  key_column: "serial",
  nautobot_field: "serial",
  match_mode: "match",
  case_insensitive: false,
  filters: {},
  counts: { only_in_file: 1, only_in_nautobot: 1 },
  columns: ["data", "site"],
  partial: false,
  rows: [
    { side: "only_in_file", value: "SN1", device_name: "", device_location: "", file_data: "x", file_site: "" },
    { side: "only_in_nautobot", value: "SN2", device_name: "dev1", device_location: "Berlin", file_data: "", file_site: "" },
    { side: "without_value", value: "", device_name: "dev2", device_location: "Rome", file_data: "", file_site: "" },
    { side: "bogus", value: "ignored" },
  ],
};

describe("parseCompareResponse", () => {
  it("reads the sides and drops unknown rows and empty file cells", () => {
    const data = parseCompareResponse(RESPONSE);
    expect(data).not.toBeNull();
    const sides = splitSides(data!.rows);
    expect(sides.onlyInFile).toEqual([
      { side: "only_in_file", value: "SN1", deviceName: "", deviceLocation: "", fileValues: { data: "x" } },
    ]);
    expect(sides.onlyInNautobot[0].deviceName).toBe("dev1");
    expect(sides.withoutValue[0].deviceLocation).toBe("Rome");
    expect(data!.rows).toHaveLength(3);
    expect(data!.rawRows).toHaveLength(4);
    expect(data!.counts.only_in_file).toBe(1);
  });

  it("returns null for a malformed answer", () => {
    expect(parseCompareResponse(null)).toBeNull();
    expect(parseCompareResponse({ rows: "x", counts: {} })).toBeNull();
    expect(parseCompareResponse({ rows: [], counts: [] })).toBeNull();
  });

  it("turns non-numeric counts into zero", () => {
    const data = parseCompareResponse({ ...RESPONSE, counts: { only_in_file: "7", matched_keys: 2 } });
    expect(data!.counts).toEqual({ only_in_file: 0, matched_keys: 2 });
  });
});

describe("visibleRows", () => {
  it("shows every row up to the limit and a sample above it", () => {
    const rows = Array.from({ length: 51 }, (_, index) => index);
    expect(visibleRows(rows.slice(0, 50), 50)).toEqual({ shown: rows.slice(0, 50), hidden: 0 });
    const cut = visibleRows(rows, 50);
    expect(cut.shown).toHaveLength(SAMPLE_ROWS);
    expect(cut.hidden).toBe(51 - SAMPLE_ROWS);
  });

  it("never shows more than the limit, even when the sample is bigger", () => {
    expect(visibleRows([1, 2, 3, 4, 5], 3)).toEqual({ shown: [1, 2, 3], hidden: 2 });
  });
});

describe("usedFileColumns", () => {
  it("keeps the first columns that hold a value", () => {
    const rows = parseCompareResponse(RESPONSE)!.rows;
    expect(usedFileColumns(rows, ["data", "site", "x"], 3)).toEqual(["data"]);
    expect(usedFileColumns(rows, ["data"], 0)).toEqual([]);
  });
});

describe("compareCsv", () => {
  it("starts with a byte order mark, holds every stored row and guards formulas", () => {
    const data = parseCompareResponse({
      ...RESPONSE,
      rows: [{ side: "only_in_file", value: "=1+1", device_name: "", file_data: "a,b" }],
    })!;
    const csv = compareCsv(data);
    expect(csv.startsWith("﻿side,value")).toBe(true);
    expect(csv).toContain("'=1+1");
    expect(csv).toContain('"a,b"');
  });
});

describe("names", () => {
  it("builds a safe file name", () => {
    expect(compareFileName("data/My Compare.csv")).toBe("my-compare-compare.csv");
    expect(compareFileName("../")).toBe("file-compare.csv");
  });

  it("labels known fields and keeps unknown ones", () => {
    expect(fieldLabel("primary_ip4")).toBe("primary IPv4 address");
    expect(fieldLabel("custom")).toBe("custom");
  });
});

describe("parseCompareProposal", () => {
  const payload = {
    kind: "compare_result",
    handle: "res_0123456789ab",
    repository: "Gitea CSV",
    file: "data/compare.csv",
    key_column: "serial",
    nautobot_field: "serial",
    match_mode: "contains",
    case_insensitive: true,
    counts: { only_in_file: 3 },
    partial: true,
    inline_limit: 25,
  };

  it("reads a well-formed payload", () => {
    expect(parseCompareProposal(payload)).toEqual({
      handle: "res_0123456789ab",
      repository: "Gitea CSV",
      file: "data/compare.csv",
      keyColumn: "serial",
      nautobotField: "serial",
      matchMode: "contains",
      caseInsensitive: true,
      counts: { only_in_file: 3 },
      partial: true,
      inlineLimit: 25,
    });
  });

  it("refuses a bad handle or counts and defaults the rest", () => {
    expect(parseCompareProposal({ ...payload, handle: "res_zz" })).toBeNull();
    expect(parseCompareProposal({ ...payload, handle: undefined })).toBeNull();
    expect(parseCompareProposal({ ...payload, counts: undefined })).toBeNull();
    const defaults = parseCompareProposal({
      handle: "res_0123456789ab",
      counts: {},
      match_mode: "regex",
      inline_limit: -3,
    });
    expect(defaults).toMatchObject({ matchMode: "match", inlineLimit: DEFAULT_INLINE_LIMIT, partial: false });
  });
});
