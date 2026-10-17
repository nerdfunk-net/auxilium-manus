import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAssistantSessionStore } from "@/components/features/ai-assistant/store/assistant-session-store";

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

describe("auth-store session expiry", () => {
  function seededClient(): QueryClient {
    const client = new QueryClient();
    client.setQueryData(["workflows", "list"], [{ id: 1, name: "previous user's workflow" }]);
    return client;
  }

  it("login clears the query cache", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ user: { id: 2, username: "b" } }), { status: 200 }),
      ),
    );
    const client = seededClient();

    await useAuthStore.getState().login({ username: "b", password: "x" }, client);

    expect(client.getQueryData(["workflows", "list"])).toBeUndefined();
  });

  it("expireSession clears the cache, the assistant chats and the user", () => {
    const client = seededClient();
    const resetAll = vi.spyOn(useAssistantSessionStore.getState(), "resetAll");
    useAuthStore.setState({
      user: { id: 1, username: "a" } as never,
      error: "stale",
      isLoading: true,
    });

    useAuthStore.getState().expireSession(client);

    expect(client.getQueryData(["workflows", "list"])).toBeUndefined();
    expect(resetAll).toHaveBeenCalled();
    expect(useAuthStore.getState()).toMatchObject({ user: null, error: null, isLoading: false });
  });
});

describe("auth-store token lifetime", () => {
  it("keeps expires_in from the login response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ user: { id: 2, username: "b" }, expires_in: 300 }), {
          status: 200,
        }),
      ),
    );
    await useAuthStore.getState().login({ username: "b", password: "x" });
    expect(useAuthStore.getState().expiresInSeconds).toBe(300);
  });

  it("ignores a missing or invalid lifetime", () => {
    useAuthStore.getState().setExpiresInSeconds(120);
    useAuthStore.getState().setExpiresInSeconds(0);
    expect(useAuthStore.getState().expiresInSeconds).toBeNull();
  });
});
