import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "./auth-store";

function mockLoginResponse(status: number) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: "x" }), { status })),
  );
}

beforeEach(() => {
  useAuthStore.setState({ user: null, error: null, isLoading: false });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("auth-store login errors", () => {
  it.each([
    [401, "Invalid username or password"],
    [429, "Too many login attempts. Please wait a few minutes and try again."],
    [502, "Authentication service unavailable. Please try again later."],
  ])("maps status %i to a distinct message", async (status, message) => {
    mockLoginResponse(status);
    await expect(
      useAuthStore.getState().login({ username: "a", password: "b" }),
    ).rejects.toThrow(message);
    expect(useAuthStore.getState().error).toBe(message);
  });
});
