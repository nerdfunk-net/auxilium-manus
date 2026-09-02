"use client";

import { useMutation } from "@tanstack/react-query";

import { useToast } from "@/hooks/use-toast";
import type { AuthUser } from "@/lib/auth";
import { useAuthStore } from "@/lib/auth-store";

interface ChangePasswordInput {
  current_password: string;
  new_password: string;
}

async function changePassword(data: ChangePasswordInput): Promise<AuthUser> {
  // Dedicated route (not the generic proxy): the backend now returns a fresh
  // session because change_password bumps token_version and invalidates the
  // caller's current token. The route re-sets the auth cookie and returns
  // { user }.
  const response = await fetch("/api/auth/change-password", {
    body: JSON.stringify(data),
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });

  const payload = (await response.json().catch(() => null)) as
    | { user?: AuthUser; message?: string }
    | null;

  if (!response.ok || !payload?.user) {
    throw new Error(payload?.message ?? "Could not change password");
  }

  return payload.user;
}

export function useChangePasswordMutation() {
  const { toast } = useToast();
  const setUser = useAuthStore((state) => state.setUser);

  return useMutation({
    mutationFn: changePassword,
    onSuccess: (user) => {
      // The response is the authoritative source: must_change_password is
      // false again, clearing the forced dialog everywhere it's read from.
      setUser(user);
      toast({ title: "Password changed", description: "Your password has been updated." });
    },
    onError: (error: Error) => {
      toast({
        title: "Could not change password",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}
