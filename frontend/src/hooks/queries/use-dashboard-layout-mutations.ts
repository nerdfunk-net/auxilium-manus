"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  DashboardLayoutResponse,
  DashboardLayoutUpdatePayload,
} from "@/components/features/dashboard/types/dashboard-layout-api";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useDashboardLayoutMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const saveLayout = useMutation({
    mutationFn: (payload: DashboardLayoutUpdatePayload) =>
      apiCall<DashboardLayoutResponse>("dashboard/layout", {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.layout() });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  return { saveLayout };
}
