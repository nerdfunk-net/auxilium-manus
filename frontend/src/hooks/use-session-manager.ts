"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

import type { AuthUser } from "@/lib/auth";
import { useAuthStore } from "@/lib/auth-store";

interface SessionConfig {
  refreshInterval?: number;
  activityTimeout?: number;
  checkInterval?: number;
}

const DEFAULT_CONFIG: Required<SessionConfig> = {
  refreshInterval: 20 * 60 * 1000, // Refresh every 20 minutes when active
  activityTimeout: 25 * 60 * 1000, // Consider inactive after 25 minutes
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
    return Date.now() - lastActivityRef.current < finalConfig.activityTimeout;
  }, [finalConfig.activityTimeout]);

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
          try {
            await logout();
          } catch {
            // Cookie may already be cleared; still leave the app.
          }
          if (typeof window !== "undefined") {
            window.location.replace("/login");
          }
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
  }, [logout, setUser]);

  useEffect(() => {
    if (!user) {
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
        checkIntervalRef.current = null;
      }
      return;
    }

    checkIntervalRef.current = setInterval(() => {
      if (!isUserActive()) return;

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
