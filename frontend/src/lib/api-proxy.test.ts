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

  it("cancels the backend request when the browser request is aborted", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await proxyRequest({
      path: ["ai", "chat"],
      request: new Request("http://next.internal/api/proxy/ai/chat", {
        method: "POST",
        body: "{}",
        signal: controller.signal,
      }),
    });

    const sentSignal = fetchMock.mock.calls[0][1].signal as AbortSignal;
    expect(sentSignal.aborted).toBe(false);
    controller.abort();
    expect(sentSignal.aborted).toBe(true);
  });

  it("refuses a cross-site state-changing request (S1-09)", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = (await proxyRequest({
      path: ["workflows"],
      request: new Request("http://next.internal/api/proxy/workflows", {
        method: "POST",
        body: "{}",
        headers: { "sec-fetch-site": "cross-site" },
      }),
    })) as { status: number };

    expect(result.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 413 for a body over the limit, declared or streamed (S1-10)", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const big = new Uint8Array(26 * 1024 * 1024);

    const declared = (await proxyRequest({
      path: ["workflows"],
      request: new Request("http://next.internal/api/proxy/workflows", {
        method: "POST",
        body: big,
        headers: { "content-length": String(big.byteLength) },
      }),
    })) as { status: number };
    expect(declared.status).toBe(413);

    const streamed = (await proxyRequest({
      path: ["workflows"],
      request: new Request("http://next.internal/api/proxy/workflows", {
        method: "POST",
        body: big,
      }),
    })) as { status: number };
    expect(streamed.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards a 12 MB body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const body = new Uint8Array(12 * 1024 * 1024);

    await proxyRequest({
      path: ["workflows"],
      request: new Request("http://next.internal/api/proxy/workflows", {
        method: "POST",
        body,
      }),
    });

    expect((fetchMock.mock.calls[0][1].body as ArrayBuffer).byteLength).toBe(body.byteLength);
  });
});
