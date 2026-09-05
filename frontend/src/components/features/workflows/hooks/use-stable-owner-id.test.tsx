import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { AuthUser } from "@/lib/auth";
import { useAuthStore } from "@/lib/auth-store";

import { useStableOwnerId } from "./use-stable-owner-id";

const TEST_USER_DEFAULTS: Omit<AuthUser, "id"> = {
  username: "test-user",
  is_active: true,
  must_change_password: false,
  roles: [],
  permissions: [],
};

function setAuthUser(id: number | null) {
  useAuthStore.setState({
    user: id === null ? null : { ...TEST_USER_DEFAULTS, id },
  });
}

beforeEach(() => {
  setAuthUser(null);
});

describe("useStableOwnerId", () => {
  it("reports null while auth has not resolved yet", () => {
    const { result } = renderHook(() => useStableOwnerId());

    expect(result.current.authUserId).toBeNull();
    expect(result.current.ownerIdRef.current).toBeNull();
  });

  it("self-heals to the real id once auth resolves after mount", () => {
    // Reproduces the regression: a component (e.g. the workflow canvas) can
    // mount on a hard page load before AuthBootstrap's async /auth/me call
    // resolves. A one-shot "capture at mount" snapshot would freeze on null
    // forever; this hook must catch up once the real id becomes known.
    const { result } = renderHook(() => useStableOwnerId());
    expect(result.current.ownerIdRef.current).toBeNull();

    act(() => setAuthUser(7));

    expect(result.current.authUserId).toBe(7);
    expect(result.current.ownerIdRef.current).toBe(7);
  });

  it("keeps the last known id after a logout clears the live auth state", () => {
    const { result } = renderHook(() => useStableOwnerId());
    act(() => setAuthUser(7));
    expect(result.current.ownerIdRef.current).toBe(7);

    act(() => setAuthUser(null));

    expect(result.current.authUserId).toBeNull();
    expect(result.current.ownerIdRef.current).toBe(7);
  });

  it("picks up the real id immediately when auth is already resolved at mount", () => {
    setAuthUser(3);

    const { result } = renderHook(() => useStableOwnerId());

    expect(result.current.authUserId).toBe(3);
    expect(result.current.ownerIdRef.current).toBe(3);
  });
});
