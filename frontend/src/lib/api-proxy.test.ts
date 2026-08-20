import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/server", () => {
  class FakeNextResponse {
    body: BodyInit | null;
    status: number;
    headers: Headers;

    constructor(body: BodyInit | null, init?: { headers?: Headers; status?: number }) {
      this.body = body;
      this.status = init?.status ?? 200;
      this.headers = init?.headers ?? new Headers();
    }

    static json(data: unknown, init?: { headers?: Headers; status?: number }) {
      return new FakeNextResponse(JSON.stringify(data), init);
    }
  }

  return { NextResponse: FakeNextResponse };
});

vi.mock("next/headers", () => ({
  cookies: () => ({ get: () => undefined }),
}));

import { normalizeProxyPath, proxyRequest } from "./api-proxy";

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

describe("proxyRequest", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("strips a Location header from the backend response", async () => {
    const backendResponse = new Response("redirecting", {
      status: 302,
      headers: { Location: "https://evil.example/phish" },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(backendResponse),
    );

    const result = (await proxyRequest({
      path: ["workflows"],
      request: new Request("http://next.internal/api/proxy/workflows"),
    })) as { headers: Headers };

    expect(result.headers.get("location")).toBeNull();
  });
});
