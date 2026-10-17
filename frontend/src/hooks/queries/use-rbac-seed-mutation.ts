"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

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
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (removeExisting: boolean) =>
      apiCall<RbacSeedResult>(`system/rbac/seed?remove_existing=${removeExisting}`, {
        method: "POST",
      }),
    // Seeding rewrites permissions and roles: the cached RBAC lists would show the old ones.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.rbac.all }),
    onError: (error: Error) => {
      toast({ title: "RBAC seed failed", description: error.message, variant: "destructive" });
    },
  });
}
