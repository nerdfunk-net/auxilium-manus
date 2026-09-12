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

  it("strips x-real-ip and forwarded but preserves x-forwarded-for (T1)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await proxyRequest({
      path: ["workflows"],
      request: new Request("http://next.internal/api/proxy/workflows", {
        headers: {
          "x-forwarded-for": "203.0.113.9",
          "x-real-ip": "203.0.113.9",
          forwarded: "for=203.0.113.9",
        },
      }),
    });

    const sentHeaders = fetchMock.mock.calls[0][1].headers as Headers;
    expect(sentHeaders.get("x-forwarded-for")).toBe("203.0.113.9");
    expect(sentHeaders.get("x-real-ip")).toBeNull();
    expect(sentHeaders.get("forwarded")).toBeNull();
  });
});
