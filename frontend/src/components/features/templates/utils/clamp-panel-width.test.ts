import { describe, expect, it } from "vitest";

import {
  clampPanelWidth,
  DEFAULT_VARIABLES_WIDTH,
  MAX_VARIABLES_WIDTH,
  MIN_VARIABLES_WIDTH,
} from "./clamp-panel-width";

describe("clampPanelWidth", () => {
  it("clamps values below the minimum up to the minimum", () => {
    expect(clampPanelWidth(0)).toBe(MIN_VARIABLES_WIDTH);
    expect(clampPanelWidth(-500)).toBe(MIN_VARIABLES_WIDTH);
    expect(clampPanelWidth(MIN_VARIABLES_WIDTH - 1)).toBe(MIN_VARIABLES_WIDTH);
  });

  it("clamps values above the maximum down to the maximum", () => {
    expect(clampPanelWidth(9999)).toBe(MAX_VARIABLES_WIDTH);
    expect(clampPanelWidth(MAX_VARIABLES_WIDTH + 1)).toBe(MAX_VARIABLES_WIDTH);
  });

  it("rounds in-range values to whole pixels", () => {
    expect(clampPanelWidth(400.4)).toBe(400);
    expect(clampPanelWidth(400.6)).toBe(401);
  });

  it("falls back to the default for non-finite input", () => {
    expect(clampPanelWidth(Number.NaN)).toBe(DEFAULT_VARIABLES_WIDTH);
    expect(clampPanelWidth(Number.POSITIVE_INFINITY)).toBe(DEFAULT_VARIABLES_WIDTH);
  });
});
