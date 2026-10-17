import { beforeEach, describe, expect, it, vi } from "vitest";

const proxyRequest = vi.hoisted(() => vi.fn());
const cookieSet = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api-proxy", () => ({ proxyRequest }));
vi.mock("next/headers", () => ({ cookies: async () => ({ set: cookieSet }) }));

import { AUTH_COOKIE_NAME } from "@/lib/auth";

import { POST } from "./route";

const USER = {
  id: 1,
  username: "tester",
  is_active: true,
  must_change_password: false,
  roles: ["viewer"],
  permissions: ["workflows:read"],
};

function login(body: unknown = { username: "tester", password: "x" }, headers: HeadersInit = {}) {
  return POST(
    new Request("http://app.internal/api/auth/login", {
      method: "POST",
      headers,
      body: typeof body === "string" ? body : JSON.stringify(body),
    }),
  );
}

function backend(tokenResponse: Response, meResponse?: Response) {
  proxyRequest.mockReset();
  proxyRequest.mockResolvedValueOnce(tokenResponse);
  if (meResponse) proxyRequest.mockResolvedValueOnce(meResponse);
}

beforeEach(() => {
  cookieSet.mockReset();
  proxyRequest.mockReset();
});

describe("POST /api/auth/login", () => {
  it("sets the HttpOnly session cookie and never puts the token in the response body", async () => {
    backend(
      Response.json({ access_token: "secret-token", expires_in: 3600 }),
      Response.json(USER),
    );

    const response = await login();
    const text = await response.text();

    expect(response.status).toBe(200);
    expect(JSON.parse(text)).toEqual({ user: USER, expires_in: 3600 });
    expect(text).not.toContain("secret-token");
    expect(cookieSet).toHaveBeenCalledWith(AUTH_COOKIE_NAME, "secret-token", {
      httpOnly: true,
      maxAge: 3600,
      path: "/",
      sameSite: "lax",
      secure: false,
    });
  });

  it("marks the cookie Secure behind a TLS-terminating proxy", async () => {
    backend(
      Response.json({ access_token: "t", expires_in: 60 }),
      Response.json(USER),
    );

    await login(undefined, { "x-forwarded-proto": "https" });

    expect(cookieSet.mock.calls[0][2]).toMatchObject({ secure: true });
  });

  it.each([
    [401, 401, "Invalid username or password"],
    [429, 429, "Too many login attempts"],
    [500, 502, "Authentication service unavailable"],
  ])("backend %i answers %i and sets no cookie", async (backendStatus, status, message) => {
    backend(new Response("{}", { status: backendStatus }));

    const response = await login();

    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ message });
    expect(cookieSet).not.toHaveBeenCalled();
  });

  it("rejects a request body that is not JSON", async () => {
    const response = await login("not json");

    expect(response.status).toBe(400);
    expect(proxyRequest).not.toHaveBeenCalled();
    expect(cookieSet).not.toHaveBeenCalled();
  });

  it("sets no cookie when the token payload is malformed", async () => {
    backend(Response.json({ access_token: 123 }));

    const response = await login();

    expect(response.status).toBe(502);
    expect(cookieSet).not.toHaveBeenCalled();
  });

  it("sets no cookie when the user cannot be loaded", async () => {
    backend(
      Response.json({ access_token: "t", expires_in: 60 }),
      new Response("{}", { status: 500 }),
    );

    const response = await login();

    expect(response.status).toBe(502);
    expect(cookieSet).not.toHaveBeenCalled();
  });
});
