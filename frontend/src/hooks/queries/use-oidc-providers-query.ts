"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface OidcProvider {
  provider_id: string;
  name: string;
  description?: string | null;
  icon?: string | null;
  display_order: number;
}

export interface OidcProvidersResponse {
  providers: OidcProvider[];
  allow_traditional_login: boolean;
}

const EMPTY_PROVIDERS: OidcProvidersResponse = {
  providers: [],
  allow_traditional_login: true,
};

export function useOidcProvidersQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.oidc.providers(),
    queryFn: async () => {
      try {
        return await apiCall<OidcProvidersResponse>("auth/oidc/providers");
      } catch {
        return EMPTY_PROVIDERS;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}
