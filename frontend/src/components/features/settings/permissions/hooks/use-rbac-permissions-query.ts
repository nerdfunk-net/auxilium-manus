"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { Permission } from "../types";

export function useRbacPermissionsQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.rbac.permissions(),
    queryFn: async () => apiCall<Permission[]>("rbac/permissions", { method: "GET" }),
    staleTime: 5 * 60 * 1000,
  });
}
