"use client";

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

export function useSessionManager(config: SessionConfig = EMPTY_CONFIG) {
  const finalConfig = { ...DEFAULT_CONFIG, ...config };
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const setUser = useAuthStore((state) => state.setUser);

  const lastActivityRef = useRef(0);
  const lastRefreshRef = useRef(0);
  const checkIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isRefreshingRef = useRef(false);

  useEffect(() => {
    lastActivityRef.current = Date.now();
    lastRefreshRef.current = Date.now();
  }, []);

  const updateActivity = useCallback(() => {
    lastActivityRef.current = Date.now();
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
    return Date.now() - lastActivityRef.current < finalConfig.idleLogoutTimeout;
  }, [finalConfig.idleLogoutTimeout]);

  const forceLogout = useCallback(
    async (reason: "idle" | "expired"): Promise<void> => {
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
        checkIntervalRef.current = null;
      }
      try {
        await logout();
      } catch {
        // Cookie may already be cleared; still leave the app.
      }
      if (typeof window !== "undefined") {
        window.location.replace(`/login?reason=${reason}`);
      }
    },
    [logout],
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

      const data = (await response.json()) as { user?: AuthUser };
      if (data.user) {
        setUser(data.user);
      }
      lastRefreshRef.current = Date.now();
      return true;
    } catch (error) {
      console.error("Session Manager: Refresh error:", error);
      return false;
    } finally {
      isRefreshingRef.current = false;
    }
  }, [forceLogout, setUser]);

  useEffect(() => {
    if (!user) {
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
        checkIntervalRef.current = null;
      }
      return;
    }

    checkIntervalRef.current = setInterval(() => {
      if (!isUserActive()) {
        void forceLogout("idle");
        return;
      }

      const timeSinceRefresh = Date.now() - lastRefreshRef.current;
      if (timeSinceRefresh >= finalConfig.refreshInterval && !isRefreshingRef.current) {
        void refreshSession();
      }
    }, finalConfig.checkInterval);

    return () => {
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
        checkIntervalRef.current = null;
      }
    };
  }, [
    user,
    isUserActive,
    forceLogout,
    refreshSession,
    finalConfig.refreshInterval,
    finalConfig.checkInterval,
  ]);

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
      getTimeSinceActivity: () => Date.now() - lastActivityRef.current,
      refreshSession,
    }),
    [isUserActive, refreshSession],
  );
}
