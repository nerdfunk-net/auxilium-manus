"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef } from "react";

import type { AuthUser } from "@/lib/auth";
import { useAuthStore } from "@/lib/auth-store";

interface SessionConfig {
  refreshInterval?: number;
  idleLogoutTimeout?: number;
  checkInterval?: number;
}

const DEFAULT_CONFIG: Required<SessionConfig> = {
  refreshInterval: 15 * 60 * 1000, // Renew the session every 15 minutes while active
  idleLogoutTimeout: 20 * 60 * 1000, // Log out after 20 minutes of inactivity
  checkInterval: 60 * 1000, // Check every minute
};

const EMPTY_CONFIG: SessionConfig = {};

/**
 * How often to renew the session. The access token may live anywhere from 1 minute to a day
 * (`ACCESS_TOKEN_EXPIRE_MINUTES`): renew at half of its lifetime when that is shorter than the
 * default, otherwise a short token expires between two renewals while the user is working.
 */
export function effectiveRefreshInterval(
  defaultMs: number,
  expiresInSeconds: number | null,
): number {
  if (expiresInSeconds === null || expiresInSeconds <= 0) return defaultMs;
  return Math.min(defaultMs, expiresInSeconds * 500);
}

// One activity clock shared by every tab of this browser (S1-05): a tab is only idle when ALL
// tabs are idle, so a background tab cannot sign the user out while another one is in use.
const ACTIVITY_KEY = "manus.lastActivity";

function readSharedActivity(): number {
  try {
    return Number(localStorage.getItem(ACTIVITY_KEY)) || 0;
  } catch {
    return 0; // private mode / blocked storage: tab-local clock only
  }
}

export function useSessionManager(config: SessionConfig = EMPTY_CONFIG) {
  const {
    refreshInterval: configuredRefreshInterval = DEFAULT_CONFIG.refreshInterval,
    idleLogoutTimeout = DEFAULT_CONFIG.idleLogoutTimeout,
    checkInterval = DEFAULT_CONFIG.checkInterval,
  } = config;
  const expiresInSeconds = useAuthStore((state) => state.expiresInSeconds);
  const setExpiresInSeconds = useAuthStore((state) => state.setExpiresInSeconds);
  const refreshInterval = effectiveRefreshInterval(configuredRefreshInterval, expiresInSeconds);
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const setUser = useAuthStore((state) => state.setUser);
  const router = useRouter();
  const queryClient = useQueryClient();

  const lastActivityRef = useRef(0);
  const lastRefreshRef = useRef(0);
  const checkIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isRefreshingRef = useRef(false);

  useEffect(() => {
    lastActivityRef.current = Date.now();
    lastRefreshRef.current = Date.now();
  }, []);

  const updateActivity = useCallback(() => {
    const now = Date.now();
    lastActivityRef.current = now;
    try {
      localStorage.setItem(ACTIVITY_KEY, String(now));
    } catch {
      // storage unavailable: fall back to the tab-local clock
    }
  }, []);

  const activityEvents = useMemo(
    () => [
      "mousedown",
      "mousemove",
      "keypress",
      "scroll",
      "touchstart",
      "click",
      "focus",
    ],
    [],
  );

  useEffect(() => {
    activityEvents.forEach((event) => {
      document.addEventListener(event, updateActivity, { passive: true });
    });
    return () => {
      activityEvents.forEach((event) => {
        document.removeEventListener(event, updateActivity);
      });
    };
  }, [updateActivity, activityEvents]);

  const isUserActive = useCallback((): boolean => {
    const lastActivity = Math.max(lastActivityRef.current, readSharedActivity());
    return Date.now() - lastActivity < idleLogoutTimeout;
  }, [idleLogoutTimeout]);

  const forceLogout = useCallback(
    async (reason: "idle" | "expired"): Promise<void> => {
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
        checkIntervalRef.current = null;
      }
      try {
        // Pass queryClient so cached data (device configs, run results, etc.)
        // is dropped explicitly, same as a manual sign-out — we no longer
        // rely on a hard reload to blow away memory (see router.replace below).
        // An idle timeout ends only this browser's cookie; an expired session or an explicit
        // sign-out revokes every session of the user.
        await logout(queryClient, { scope: reason === "idle" ? "local" : "global" });
      } catch {
        // Cookie may already be cleared; still leave the app.
      }
      // A soft (client-side) navigation, not window.location.replace: a hard
      // reload wipes the in-memory canvasDraft singleton
      // (use-workflow-builder-store.ts) that lets an unsaved workflow survive
      // navigating away and back, so it would silently discard the user's
      // in-progress edits on the next login instead of restoring them.
      // The draft is pinned to its owner (CanvasDraft.userId), so keeping it
      // in memory only lets the *same* user resume — a different account
      // logging in on this tab has it cleared by DashboardShell's
      // reconcileDraftOwner effect and by the restore guard in
      // use-workflow-canvas-core.ts.
      router.replace(`/login?reason=${reason}`);
      router.refresh();
    },
    [logout, queryClient, router],
  );

  const refreshSession = useCallback(async (): Promise<boolean> => {
    if (isRefreshingRef.current) return false;
    isRefreshingRef.current = true;

    try {
      const response = await fetch("/api/auth/refresh", {
        credentials: "include",
        method: "POST",
      });

      if (!response.ok) {
        if (response.status === 401) {
          await forceLogout("expired");
        }
        return false;
      }

      const data = (await response.json()) as { user?: AuthUser; expires_in?: number };
      if (data.user) {
        setUser(data.user);
      }
      if (typeof data.expires_in === "number") {
        setExpiresInSeconds(data.expires_in);
      }
      lastRefreshRef.current = Date.now();
      return true;
    } catch (error) {
      console.error("Session Manager: Refresh error:", error);
      return false;
    } finally {
      isRefreshingRef.current = false;
    }
  }, [forceLogout, setUser, setExpiresInSeconds]);

  // Shared by the interval tick and the visibility handler. Wall-clock based, so
  // it is correct no matter how long the browser throttled the interval.
  const runSessionCheck = useCallback(() => {
    if (!isUserActive()) {
      void forceLogout("idle");
      return;
    }

    const timeSinceRefresh = Date.now() - lastRefreshRef.current;
    if (timeSinceRefresh >= refreshInterval && !isRefreshingRef.current) {
      void refreshSession();
    }
  }, [isUserActive, forceLogout, refreshSession, refreshInterval]);

  useEffect(() => {
    if (!user) {
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
        checkIntervalRef.current = null;
      }
      return;
    }

    checkIntervalRef.current = setInterval(runSessionCheck, checkInterval);

    // Background tabs get their timers throttled/suspended. Re-evaluate the
    // session the moment the tab becomes visible instead of waiting for the next
    // (possibly stale) tick: idle > timeout logs out now, otherwise keeps going.
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        runSessionCheck();
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
        checkIntervalRef.current = null;
      }
    };
  }, [user, runSessionCheck, checkInterval]);

  useEffect(() => {
    return () => {
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
        checkIntervalRef.current = null;
      }
    };
  }, []);

  return useMemo(
    () => ({
      isUserActive,
      getTimeSinceActivity: () =>
        Date.now() - Math.max(lastActivityRef.current, readSharedActivity()),
      refreshSession,
    }),
    [isUserActive, refreshSession],
  );
}
