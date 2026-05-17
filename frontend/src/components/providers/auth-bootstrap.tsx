"use client";

import { useEffect } from "react";

import { useAuthStore } from "@/lib/auth-store";

export function AuthBootstrap() {
  const loadCurrentUser = useAuthStore((state) => state.loadCurrentUser);

  useEffect(() => {
    void loadCurrentUser();
  }, [loadCurrentUser]);

  return null;
}
