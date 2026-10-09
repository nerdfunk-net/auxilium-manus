import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser } from "@/lib/auth";
import { useAuthStore } from "@/lib/auth-store";

import { useSessionManager } from "./use-session-manager";

const routerMock = { replace: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));

const USER: AuthUser = {
  id: 1,
  username: "tester",
  is_active: true,
  must_change_password: false,
  roles: [],
  permissions: [],
};

const IDLE_MS = 20 * 60 * 1000;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function showTab() {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

const logout = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  vi.useFakeTimers();
  routerMock.replace.mockClear();
  routerMock.refresh.mockClear();
  logout.mockClear();
  useAuthStore.setState({ user: USER, logout });
});

afterEach(() => {
  vi.useRealTimers();
  useAuthStore.setState({ user: null });
});

describe("useSessionManager visibility handling", () => {
  it("logs out immediately when the tab is shown after exceeding the idle window", async () => {
    renderHook(() => useSessionManager(), { wrapper });

    // Time passes with no interval tick delivered (throttled background tab).
    vi.setSystemTime(Date.now() + IDLE_MS + 1000);
    await act(async () => {
      showTab();
    });

    expect(logout).toHaveBeenCalledTimes(1);
    expect(routerMock.replace).toHaveBeenCalledWith("/login?reason=idle");
  });

  it("does not log out when the tab is shown within the idle window", async () => {
    renderHook(() => useSessionManager(), { wrapper });

    vi.setSystemTime(Date.now() + IDLE_MS - 60 * 1000);
    await act(async () => {
      showTab();
    });

    expect(logout).not.toHaveBeenCalled();
  });
});
