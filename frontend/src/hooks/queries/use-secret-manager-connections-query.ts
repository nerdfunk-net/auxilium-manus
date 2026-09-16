"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export type SecretManagerBackend = "openbao" | "infisical";

export interface SecretManagerConnectionRecord {
  id: number;
  name: string;
  backend: SecretManagerBackend;
  credential_name: string | null;
  verify_ssl: boolean;
  is_active: boolean;
  description: string | null;
  backend_config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface SecretManagerConnectionListResponse {
  connections: SecretManagerConnectionRecord[];
  total: number;
}

interface UseSecretManagerConnectionsQueryOptions {
  activeOnly?: boolean;
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseSecretManagerConnectionsQueryOptions = {};

export function useSecretManagerConnectionsQuery(
  options: UseSecretManagerConnectionsQueryOptions = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const { activeOnly = false, enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.secretManagerConnections.list(activeOnly),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (activeOnly) params.set("active_only", "true");
      const query = params.toString();
      return apiCall<SecretManagerConnectionListResponse>(
        `secret-manager/connections${query ? `?${query}` : ""}`,
        { method: "GET" },
      );
    },
    enabled,
    staleTime: 30 * 1000,
  });
}
