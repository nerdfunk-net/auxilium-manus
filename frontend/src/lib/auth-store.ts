"use client";

import type { QueryClient } from "@tanstack/react-query";
import { create } from "zustand";

import { useAssistantSessionStore } from "@/components/features/ai-assistant/store/assistant-session-store";

import type { AuthUser, LoginResponse } from "@/lib/auth";

interface AuthState {
  user: AuthUser | null;
  /** Lifetime of the current access token in seconds, when the server reported it. */
  expiresInSeconds: number | null;
  isLoading: boolean;
  error: string | null;
  loadCurrentUser: () => Promise<void>;
  login: (
    credentials: { username: string; password: string },
    queryClient?: QueryClient,
  ) => Promise<void>;
  /** The server refused the session (401): drop everything the previous user could see. */
  expireSession: (queryClient?: QueryClient) => void;
  logout: (queryClient?: QueryClient, options?: { scope?: "global" | "local" }) => Promise<void>;
  setUser: (user: AuthUser) => void;
  setExpiresInSeconds: (seconds: number | null) => void;
  markPasswordChangeRequired: () => void;
}

function loginErrorMessage(status: number): string {
  if (status === 429) {
    return "Too many login attempts. Please wait a few minutes and try again.";
  }
  if (status >= 500) {
    return "Authentication service unavailable. Please try again later.";
  }
  return "Invalid username or password";
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  expiresInSeconds: null,
  setExpiresInSeconds: (seconds) => {
    set({ expiresInSeconds: typeof seconds === "number" && seconds > 0 ? seconds : null });
  },
  isLoading: false,
  error: null,
  setUser: (user) => {
    set({ user });
  },
  markPasswordChangeRequired: () => {
    set((state) =>
      state.user ? { user: { ...state.user, must_change_password: true } } : {},
    );
  },
  loadCurrentUser: async () => {
    set({ isLoading: true, error: null });

    try {
      const response = await fetch("/api/auth/me", {
        cache: "no-store",
        credentials: "include",
      });

      if (!response.ok) {
        set({ isLoading: false, user: null });
        return;
      }

      const payload = (await response.json()) as LoginResponse;
      set({ isLoading: false, user: payload.user });
    } catch {
      set({
        error: "Could not load current user",
        isLoading: false,
        user: null,
      });
    }
  },
  expireSession: (queryClient) => {
    // Same reasoning as logout(): a 401 redirects to /login with the SPA still in memory, so the
    // next person to sign in on this tab must not find the previous user's cached data.
    queryClient?.clear();
    useAssistantSessionStore.getState().resetAll();
    set({ user: null, isLoading: false, error: null });
  },
  login: async (credentials, queryClient) => {
    set({ isLoading: true, error: null });
    // Second line of defence: whatever the previous session left behind, a new login starts clean.
    queryClient?.clear();

    try {
      const response = await fetch("/api/auth/login", {
        body: JSON.stringify(credentials),
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        method: "POST",
      });

      if (!response.ok) {
        const message = loginErrorMessage(response.status);
        set({ error: message, isLoading: false, user: null });
        throw new Error(message);
      }

      const payload = (await response.json()) as LoginResponse;
      set({
        isLoading: false,
        user: payload.user,
        expiresInSeconds: typeof payload.expires_in === "number" ? payload.expires_in : null,
      });
    } catch (error) {
      set({
        error:
          error instanceof Error
            ? error.message
            : "Could not reach authentication service",
        isLoading: false,
        user: null,
      });
      throw error;
    }
  },
  logout: async (queryClient, options) => {
    set({ error: null, isLoading: true });

    try {
      const scope = options?.scope === "local" ? "?scope=local" : "";
      const response = await fetch(`/api/auth/logout${scope}`, {
        credentials: "include",
        method: "POST",
      });

      if (!response.ok) {
        throw new Error("Could not sign out");
      }

      // Drop cached query results (device configs, run step results, etc.)
      // so they can't survive in memory for the next person on a shared
      // machine before a full page reload.
      queryClient?.clear();
      // Assistant chats may hold device or run data; same reasoning as the cache above.
      useAssistantSessionStore.getState().resetAll();
      set({ error: null, isLoading: false, user: null });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : "Could not sign out",
        isLoading: false,
      });
      throw error;
    }
  },
}));
