"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import type { AuthUser } from "@/lib/auth";
import { useAuthStore } from "@/lib/auth-store";

interface ChangePasswordInput {
  current_password: string;
  new_password: string;
}

export function useChangePasswordMutation() {
  const { apiCall } = useApi();
  const { toast } = useToast();
  const setUser = useAuthStore((state) => state.setUser);

  return useMutation({
    mutationFn: (data: ChangePasswordInput) =>
      apiCall<AuthUser>("auth/change-password", {
        method: "POST",
        body: JSON.stringify(data),
      }),
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
