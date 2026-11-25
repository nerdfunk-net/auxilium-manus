import { describe, expect, it } from "vitest";

import {
  DEFAULT_LOCATIONS_MODE,
  isValidLocationsMode,
  locationsModeFromConfig,
} from "./nautobot-locations";

describe("locations mode", () => {
  it("accepts a missing, null or empty mode and the three known ones", () => {
    for (const config of [{}, { locations_mode: null }, { locations_mode: "" }]) {
      expect(isValidLocationsMode(config)).toBe(true);
    }
    for (const mode of ["replace", "add", "remove"]) {
      expect(isValidLocationsMode({ locations_mode: mode })).toBe(true);
    }
  });

  it("refuses an unknown or non-string mode", () => {
    expect(isValidLocationsMode({ locations_mode: "merge" })).toBe(false);
    expect(isValidLocationsMode({ locations_mode: 3 })).toBe(false);
  });

  it("shows the stored mode, replace when none, empty when invalid", () => {
    expect(locationsModeFromConfig({ locations_mode: "add" })).toBe("add");
    expect(locationsModeFromConfig({})).toBe(DEFAULT_LOCATIONS_MODE);
    expect(locationsModeFromConfig({ locations_mode: "" })).toBe("replace");
    expect(locationsModeFromConfig({ locations_mode: "merge" })).toBe("");
  });
});
