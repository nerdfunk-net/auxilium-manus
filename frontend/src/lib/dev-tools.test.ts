import { afterEach, describe, expect, it, vi } from "vitest";

import { isDevToolsEnabled } from "./dev-tools";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("isDevToolsEnabled", () => {
  it("is on only outside production and with the flag set", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("ENABLE_DEV_TOOLS", "true");
    expect(isDevToolsEnabled()).toBe(true);
  });

  it("stays off in production even when the flag is inherited from a dev .env", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("ENABLE_DEV_TOOLS", "true");
    expect(isDevToolsEnabled()).toBe(false);
  });

  it("is off without the flag, or with any value other than the string true", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("ENABLE_DEV_TOOLS", "");
    expect(isDevToolsEnabled()).toBe(false);
    vi.stubEnv("ENABLE_DEV_TOOLS", "1");
    expect(isDevToolsEnabled()).toBe(false);
  });
});
