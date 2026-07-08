"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { UserPermissions } from "../types";

export function useUserPermissionsQuery(userId: number | null) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.rbac.userPermissions(userId ?? -1),
    queryFn: async () =>
      apiCall<UserPermissions>(`rbac/users/${userId}/permissions`, { method: "GET" }),
    enabled: userId !== null,
    staleTime: 15 * 1000,
  });
}

export function useMyPermissionsQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.rbac.myPermissions(),
    queryFn: async () =>
      apiCall<UserPermissions>("rbac/users/me/permissions", { method: "GET" }),
    staleTime: 5 * 60 * 1000,
  });
}
