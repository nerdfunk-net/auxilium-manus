import { describe, expect, it, vi } from "vitest";

const proxyRequest = vi.hoisted(() => vi.fn().mockResolvedValue({ status: 200 }));

vi.mock("@/lib/api-proxy", () => ({ proxyRequest }));
vi.mock("next/server", () => ({
  NextResponse: { json: (data: unknown, init?: { status?: number }) => ({ data, status: init?.status ?? 200 }) },
}));

import { POST } from "./route";

function call(path: string[]) {
  return POST(new Request("http://app.internal/api/proxy/x", { method: "POST" }), {
    params: Promise.resolve({ path }),
  });
}

describe("generic proxy token-minting deny list (S1-03)", () => {
  it.each([
    [["auth", "login"]],
    [["auth", "refresh"]],
    [["api", "auth", "refresh"]],
    [["auth", "change-password"]],
    [["auth", "oidc", "google", "callback"]],
  ])("rejects %j", async (path) => {
    proxyRequest.mockClear();
    const response = (await call(path)) as { status: number };
    expect(response.status).toBe(404);
    expect(proxyRequest).not.toHaveBeenCalled();
  });

  it("still forwards other auth paths", async () => {
    proxyRequest.mockClear();
    await call(["auth", "me"]);
    expect(proxyRequest).toHaveBeenCalledTimes(1);
  });
});
