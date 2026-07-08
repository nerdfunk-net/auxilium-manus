"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { RbacUserListResponse } from "../types";

export function useUsersQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.users.list(),
    queryFn: async () => apiCall<RbacUserListResponse>("users", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
