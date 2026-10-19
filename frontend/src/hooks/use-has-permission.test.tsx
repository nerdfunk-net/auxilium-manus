import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useAuthStore } from "@/lib/auth-store";

import { useHasPermission } from "./use-has-permission";

beforeEach(() => {
  useAuthStore.setState({ user: null });
});

describe("useHasPermission", () => {
  it("is true when the user holds resource:action", () => {
    useAuthStore.setState({
      user: { username: "me", permissions: ["credentials:read"], roles: [] } as never,
    });
    const { result } = renderHook(() => useHasPermission("credentials", "read"));
    expect(result.current).toBe(true);
  });

  it("is false for another action or resource", () => {
    useAuthStore.setState({
      user: { username: "me", permissions: ["credentials:write"], roles: [] } as never,
    });
    expect(renderHook(() => useHasPermission("credentials", "read")).result.current).toBe(false);
    expect(renderHook(() => useHasPermission("settings", "write")).result.current).toBe(false);
  });

  it("checks the action asked for, not just the resource", () => {
    useAuthStore.setState({
      user: { username: "me", permissions: ["credentials:read"], roles: [] } as never,
    });
    expect(renderHook(() => useHasPermission("credentials", "write")).result.current).toBe(false);
  });

  it("is false before the user is known", () => {
    expect(renderHook(() => useHasPermission("credentials", "read")).result.current).toBe(false);
  });

  it("follows a change of the signed-in user", () => {
    const { result } = renderHook(() => useHasPermission("credentials", "read"));
    expect(result.current).toBe(false);
    act(() =>
      useAuthStore.setState({
        user: { username: "me", permissions: ["credentials:read"], roles: [] } as never,
      }),
    );
    expect(result.current).toBe(true);
  });
});
