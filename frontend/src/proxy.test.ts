import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { config, proxy } from "./proxy";

afterEach(() => {
  vi.unstubAllEnvs();
});

function run() {
  return proxy(new NextRequest("http://app.internal/workflows"));
}

describe("proxy (CSP middleware)", () => {
  it("issues a per-request nonce that appears in the policy and in the forwarded request", () => {
    vi.stubEnv("NODE_ENV", "production");
    const first = run();
    const second = run();
    const csp = first.headers.get("Content-Security-Policy") ?? "";
    const nonce = /'nonce-([^']+)'/.exec(csp)?.[1];
    expect(nonce).toBeTruthy();
    expect(first.headers.get("x-middleware-request-x-nonce")).toBe(nonce);
    expect(second.headers.get("Content-Security-Policy")).not.toBe(csp);
  });

  it("allows 'unsafe-eval' only outside production", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(run().headers.get("Content-Security-Policy")).not.toContain("unsafe-eval");
    vi.stubEnv("NODE_ENV", "development");
    expect(run().headers.get("Content-Security-Policy")).toContain("'unsafe-eval'");
  });

  it("forbids framing, plugins and foreign form targets, and never allows unsafe-inline scripts", () => {
    vi.stubEnv("NODE_ENV", "production");
    const csp = run().headers.get("Content-Security-Policy") ?? "";
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("form-action 'self'");
    expect(csp).toContain("connect-src 'self'");
    const scriptSrc = csp.split("; ").find((d) => d.startsWith("script-src")) ?? "";
    expect(scriptSrc).not.toContain("unsafe-inline");
    expect(scriptSrc).toContain("'strict-dynamic'");
  });

  it("does not run for API routes or static assets", () => {
    const pattern = new RegExp(`^${config.matcher[0]}$`);
    expect(pattern.test("/workflows")).toBe(true);
    expect(pattern.test("/api/proxy/x")).toBe(false);
    expect(pattern.test("/_next/static/chunk.js")).toBe(false);
  });
});
