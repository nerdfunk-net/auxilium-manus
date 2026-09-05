"use client";

import { useEffect, useRef } from "react";
import type { RefObject } from "react";

import { useAuthStore } from "@/lib/auth-store";

export interface StableOwnerId {
  /** The live selector value — null whenever auth hasn't resolved yet, or after logout. */
  authUserId: number | null;
  /**
   * The most recently known real user id. Starts equal to `authUserId` and
   * self-heals to it whenever it becomes non-null, but never regresses back
   * to null afterward (a real logout clears `authUserId` before this
   * component unmounts, but callers snapshotting "who owns this" at unmount
   * still need the real id, not null).
   */
  ownerIdRef: RefObject<number | null>;
}

/**
 * Resolves "the current user id" for callers that must stamp long-lived data
 * (e.g. a draft snapshot saved on unmount) with a stable owner, even though
 * `useAuthStore.user` is loaded asynchronously by `AuthBootstrap` and can
 * still be null on a component's first render (a hard load landing directly
 * on an authenticated page mounts before that fetch resolves). A plain
 * "capture once at mount" snapshot would freeze on that null for the whole
 * component lifetime; this hook instead keeps healing to the real id as soon
 * as it is known, while never un-learning it once a real logout clears
 * `authUserId` back to null.
 */
export function useStableOwnerId(): StableOwnerId {
  const authUserId = useAuthStore((state) => state.user?.id ?? null);
  const ownerIdRef = useRef<number | null>(authUserId);
  useEffect(() => {
    if (authUserId !== null) {
      ownerIdRef.current = authUserId;
    }
  }, [authUserId]);
  return { authUserId, ownerIdRef };
}
