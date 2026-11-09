import { describe, expect, it } from "vitest";

import { RESULT_HANDLE, configFileName, describeSize } from "./config-download";

describe("configFileName", () => {
  it("names the file after the device and the config kind", () => {
    expect(configFileName("LAB", "startup")).toBe("lab-startup-config.cfg");
  });

  it("reduces unsafe characters to a slug", () => {
    expect(configFileName("../Berlin SW/01", "running")).toBe(
      "berlin-sw-01-running-config.cfg",
    );
  });

  it("falls back when nothing is left", () => {
    expect(configFileName("///", "")).toBe("device-running-config.cfg");
  });
});

describe("describeSize", () => {
  it("shows lines and kilobytes, at least 1 KB", () => {
    expect(describeSize(1204, 39000)).toBe("1,204 lines, 38 KB");
    expect(describeSize(1, 10)).toBe("1 lines, 1 KB");
  });
});

describe("RESULT_HANDLE", () => {
  it("accepts only the server's handle format", () => {
    expect(RESULT_HANDLE.test("res_0123456789ab")).toBe(true);
    expect(RESULT_HANDLE.test("res_ZZ")).toBe(false);
    expect(RESULT_HANDLE.test("../res_0123456789ab")).toBe(false);
  });
});
