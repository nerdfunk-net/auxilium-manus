import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/lib/auth-store";

import { ApiError, isConflictError, useApi } from "./use-api";

const routerMock = { replace: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));

function setup() {
  const client = new QueryClient();
  client.setQueryData(["runs", 1], { status: "running", secret: "previous user's data" });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

beforeEach(() => {
  routerMock.replace.mockClear();
  useAuthStore.setState({ user: { id: 1, username: "a" } as never });
});

afterEach(() => {
  vi.unstubAllGlobals();
  useAuthStore.setState({ user: null });
});

describe("useApi", () => {
  it("clears the query cache on 401 and sends the user to /login", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useApi(), { wrapper });

    await expect(result.current.apiCall("runs/1")).rejects.toThrow("Authentication required");

    expect(client.getQueryData(["runs", 1])).toBeUndefined();
    expect(useAuthStore.getState().user).toBeNull();
    expect(routerMock.replace).toHaveBeenCalledWith("/login");
  });

  it("keeps the HTTP status on a failed call", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "changed" }), { status: 409 })),
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => useApi(), { wrapper });

    const error = await result.current.apiCall("workflows/1").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).message).toBe("changed");
    expect(isConflictError(error)).toBe(true);
    expect(isConflictError(new Error("x"))).toBe(false);
  });

  it("keeps an object detail on the error so callers can read structured data", async () => {
    const detail = {
      code: "credential_in_use",
      message: "Credential is still used by 1 item(s)",
      dependants: [{ kind: "workflow", id: 8, name: "Backup" }],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail }), { status: 409 })),
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => useApi(), { wrapper });

    const error = await result.current.apiCall("credentials/5").catch((e: unknown) => e);

    expect((error as ApiError).message).toBe("Credential is still used by 1 item(s)");
    expect((error as ApiError).detail).toEqual(detail);
  });

  it("has no detail object for a plain string detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "changed" }), { status: 409 })),
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => useApi(), { wrapper });

    const error = await result.current.apiCall("workflows/1").catch((e: unknown) => e);

    expect((error as ApiError).detail).toBeNull();
  });
});
