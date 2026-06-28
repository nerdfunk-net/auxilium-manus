"use client";

import { create } from "zustand";

import type { AuthUser, LoginResponse } from "@/lib/auth";

interface AuthState {
  user: AuthUser | null;
  isLoading: boolean;
  error: string | null;
  loadCurrentUser: () => Promise<void>;
  login: (credentials: { username: string; password: string }) => Promise<void>;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: false,
  error: null,
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
  login: async (credentials) => {
    set({ isLoading: true, error: null });

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
        set({
          error: "Invalid username or password",
          isLoading: false,
          user: null,
        });
        throw new Error("Invalid username or password");
      }

      const payload = (await response.json()) as LoginResponse;
      set({ isLoading: false, user: payload.user });
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
  logout: async () => {
    set({ error: null, isLoading: true });

    try {
      const response = await fetch("/api/auth/logout", {
        credentials: "include",
        method: "POST",
      });

      if (!response.ok) {
        throw new Error("Could not sign out");
      }

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
