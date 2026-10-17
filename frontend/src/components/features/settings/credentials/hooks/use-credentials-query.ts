"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { CredentialListResponse } from "../types";

interface UseCredentialsQueryOptions {
  includeExpired?: boolean;
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseCredentialsQueryOptions = {};

export function useCredentialsQuery(options: UseCredentialsQueryOptions = DEFAULT_OPTIONS) {
  const { apiCall } = useApi();
  const { includeExpired = false, enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.credentials.list(includeExpired),
    queryFn: () =>
      apiCall<CredentialListResponse>(
        `credentials?source=general&include_expired=${includeExpired ? "true" : "false"}`,
        { method: "GET" },
      ),
    enabled,
    staleTime: 30 * 1000,
  });
}
