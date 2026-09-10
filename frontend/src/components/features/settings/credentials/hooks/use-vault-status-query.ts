"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface VaultStatusResponse {
  enabled: boolean;
}

/**
 * Whether the OpenBao storage backend is available on this deployment. Pure
 * settings read on the backend — no OpenBao call. Drives whether the credential
 * form offers a "storage backend" choice.
 */
export function useVaultStatusQuery(enabled = true) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.credentials.vaultStatus(),
    queryFn: () =>
      apiCall<VaultStatusResponse>("credentials/vault/status", { method: "GET" }),
    enabled,
    staleTime: 60 * 1000,
  });
}
