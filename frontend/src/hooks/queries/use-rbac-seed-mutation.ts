"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

export interface RbacSeedResult {
  success: boolean;
  message: string;
  permissions_seeded: number;
  roles_seeded: number;
  removed_existing: boolean;
}

export function useRbacSeedMutation() {
  const { apiCall } = useApi();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (removeExisting: boolean) =>
      apiCall<RbacSeedResult>(`system/rbac/seed?remove_existing=${removeExisting}`, {
        method: "POST",
      }),
    onError: (error: Error) => {
      toast({ title: "RBAC seed failed", description: error.message, variant: "destructive" });
    },
  });
}
