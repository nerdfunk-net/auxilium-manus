"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { Role, RoleWithPermissions } from "../types";

export function useRbacRolesQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.rbac.roles(),
    queryFn: async () => apiCall<Role[]>("rbac/roles", { method: "GET" }),
    staleTime: 60 * 1000,
  });
}

export function useRbacRoleQuery(roleId: number | null) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.rbac.role(roleId ?? -1),
    queryFn: async () => apiCall<RoleWithPermissions>(`rbac/roles/${roleId}`, { method: "GET" }),
    enabled: roleId !== null,
    staleTime: 30 * 1000,
  });
}
