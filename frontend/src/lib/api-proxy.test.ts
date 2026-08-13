import { describe, expect, it, vi } from "vitest";

vi.mock("next/server", () => ({
  NextResponse: { json: () => ({}) },
}));

vi.mock("next/headers", () => ({
  cookies: () => ({ get: () => undefined }),
}));

import { normalizeProxyPath } from "./api-proxy";

describe("normalizeProxyPath", () => {
  it("prefixes /api for backend paths", () => {
    expect(normalizeProxyPath(["workflows", "1"])).toBe("/api/workflows/1");
  });

  it("keeps an existing api/ prefix", () => {
    expect(normalizeProxyPath(["api", "auth", "me"])).toBe("/api/auth/me");
  });

  it("re-encodes # in a path segment", () => {
    expect(
      normalizeProxyPath(["sources", "ise", "lab", "devices", "ndg", "myGroup#x"]),
    ).toBe("/api/sources/ise/lab/devices/ndg/myGroup%23x");
  });

  it.each([[[".."]], [["foo", ".."]], [["foo", "..", "bar"]], [[""]], [["."]]])(
    "rejects forbidden segment %j",
    (path) => {
      expect(() => normalizeProxyPath(path)).toThrow("Invalid proxy path");
    },
  );
});
