import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser } from "@/lib/auth";
import { useAuthStore } from "@/lib/auth-store";

import { effectiveRefreshInterval, useSessionManager } from "./use-session-manager";

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

// Node 25+ ships its own experimental `localStorage` global, which shadows jsdom's and is
// undefined without --localstorage-file. A plain in-memory Storage keeps these tests independent
// of the Node version.
function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => Array.from(data.keys())[index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  };
}

beforeEach(() => {
  vi.stubGlobal("localStorage", memoryStorage());
  vi.useFakeTimers();
  routerMock.replace.mockClear();
  routerMock.refresh.mockClear();
  logout.mockClear();
  useAuthStore.setState({ user: USER, logout });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
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

describe("useSessionManager shared activity (S1-05)", () => {
  it("does not log out while another tab reports activity", async () => {
    renderHook(() => useSessionManager(), { wrapper });

    vi.setSystemTime(Date.now() + IDLE_MS + 1000);
    localStorage.setItem("manus.lastActivity", String(Date.now()));
    await act(async () => {
      showTab();
    });

    expect(logout).not.toHaveBeenCalled();
    localStorage.removeItem("manus.lastActivity");
  });

  it("idle logout requests local scope", async () => {
    renderHook(() => useSessionManager(), { wrapper });

    vi.setSystemTime(Date.now() + IDLE_MS + 1000);
    await act(async () => {
      showTab();
    });

    expect(logout).toHaveBeenCalledWith(expect.anything(), { scope: "local" });
  });
});

describe("effectiveRefreshInterval", () => {
  const DEFAULT_MS = 15 * 60 * 1000;

  it("refreshes at half the token lifetime when it is shorter than 30 minutes", () => {
    expect(effectiveRefreshInterval(DEFAULT_MS, 60)).toBe(30 * 1000);
    expect(effectiveRefreshInterval(DEFAULT_MS, 10 * 60)).toBe(5 * 60 * 1000);
  });

  it("keeps the default for a long-lived token or an unknown lifetime", () => {
    expect(effectiveRefreshInterval(DEFAULT_MS, 60 * 60)).toBe(DEFAULT_MS);
    expect(effectiveRefreshInterval(DEFAULT_MS, 24 * 3600)).toBe(DEFAULT_MS);
    expect(effectiveRefreshInterval(DEFAULT_MS, null)).toBe(DEFAULT_MS);
    expect(effectiveRefreshInterval(DEFAULT_MS, 0)).toBe(DEFAULT_MS);
  });
});
