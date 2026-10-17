import { afterEach, describe, expect, it, vi } from "vitest";

import { AUTH_COOKIE_NAME, clearAuthCookie, cookieSecure, setAuthCookie } from "./auth";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("cookieSecure (S1-11)", () => {
  it("is secure when x-forwarded-proto is https", () => {
    const request = new Request("http://app.internal/x", {
      headers: { "x-forwarded-proto": "https" },
    });
    expect(cookieSecure(request)).toBe(true);
  });

  it("is not secure for plain http", () => {
    expect(cookieSecure(new Request("http://app.internal/x"))).toBe(false);
  });

  it("COOKIE_SECURE overrides the connection", () => {
    vi.stubEnv("COOKIE_SECURE", "true");
    expect(cookieSecure(new Request("http://app.internal/x"))).toBe(true);
    vi.stubEnv("COOKIE_SECURE", "false");
    expect(
      cookieSecure(new Request("http://app.internal/x", { headers: { "x-forwarded-proto": "https" } })),
    ).toBe(false);
  });
});

describe("setAuthCookie", () => {
  it("sets an HttpOnly, SameSite=lax, root-path cookie for the token lifetime", () => {
    const set = vi.fn();
    setAuthCookie({ set }, "tok", 3600, new Request("https://app.internal/x"));
    expect(set).toHaveBeenCalledWith(AUTH_COOKIE_NAME, "tok", {
      httpOnly: true,
      maxAge: 3600,
      path: "/",
      sameSite: "lax",
      secure: true,
    });
  });

  it("is not Secure on a plain-http connection, and is Secure behind a TLS proxy", () => {
    const set = vi.fn();
    setAuthCookie({ set }, "tok", 60, new Request("http://app.internal/x"));
    expect(set.mock.calls[0][2].secure).toBe(false);
    setAuthCookie(
      { set },
      "tok",
      60,
      new Request("http://app.internal/x", { headers: { "x-forwarded-proto": "https" } }),
    );
    expect(set.mock.calls[1][2].secure).toBe(true);
  });

  it("clearAuthCookie expires the same cookie immediately", () => {
    const set = vi.fn();
    clearAuthCookie({ set }, true);
    expect(set).toHaveBeenCalledWith(
      AUTH_COOKIE_NAME,
      "",
      expect.objectContaining({ httpOnly: true, maxAge: 0, path: "/", secure: true }),
    );
  });
});
