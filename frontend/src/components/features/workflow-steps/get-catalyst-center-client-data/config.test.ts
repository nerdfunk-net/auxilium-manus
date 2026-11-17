import { describe, expect, it } from "vitest";

import {
  clampLookbackHours,
  DEFAULT_LOOKBACK_HOURS,
  MAX_LOOKBACK_HOURS,
  MIN_LOOKBACK_HOURS,
  readLookbackHours,
} from "./config";

describe("clampLookbackHours", () => {
  it("clamps into the backend range and falls back for non-numbers", () => {
    expect(clampLookbackHours("0")).toBe(MIN_LOOKBACK_HOURS);
    expect(clampLookbackHours("9999")).toBe(MAX_LOOKBACK_HOURS);
    expect(clampLookbackHours("48")).toBe(48);
    expect(clampLookbackHours("")).toBe(DEFAULT_LOOKBACK_HOURS);
    expect(clampLookbackHours("abc")).toBe(DEFAULT_LOOKBACK_HOURS);
  });
});

describe("readLookbackHours", () => {
  it("reads a number and defaults anything else", () => {
    expect(readLookbackHours({ lookback_hours: 12 })).toBe(12);
    expect(readLookbackHours({ lookback_hours: 0 })).toBe(MIN_LOOKBACK_HOURS);
    expect(readLookbackHours({ lookback_hours: 9999 })).toBe(MAX_LOOKBACK_HOURS);
    expect(readLookbackHours({ lookback_hours: 12.7 })).toBe(12);
    expect(readLookbackHours({ lookback_hours: "12" })).toBe(DEFAULT_LOOKBACK_HOURS);
    expect(readLookbackHours({})).toBe(DEFAULT_LOOKBACK_HOURS);
  });
});
