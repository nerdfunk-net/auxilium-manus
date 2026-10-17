"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface OidcProviderEndpoints {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  userinfo_endpoint: string | null;
  jwks_uri: string;
  end_session_endpoint: string | null;
}

export interface OidcProviderDebugInfo {
  provider_id: string;
  name: string;
  enabled: boolean;
  client_id: string | null;
  discovery_url: string | null;
  scopes: string[];
  claim_mappings: Record<string, string>;
  auto_provision: boolean;
  default_role: string | null;
  ca_cert_path: string | null;
  ca_cert_exists: boolean | null;
  endpoints: OidcProviderEndpoints | null;
  discovery_error: string | null;
}

export interface OidcDebugStatus {
  oidc_enabled: boolean;
  allow_traditional_login: boolean;
  providers: OidcProviderDebugInfo[];
  config_path: string;
}

interface UseOidcDebugQueryOptions {
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseOidcDebugQueryOptions = {};

export function useOidcDebugQuery(options: UseOidcDebugQueryOptions = DEFAULT_OPTIONS) {
  const { apiCall } = useApi();
  const { enabled = true } = options;

  return useQuery<OidcDebugStatus>({
    queryKey: queryKeys.oidc.debug(),
    queryFn: () => apiCall("auth/oidc/debug", { method: "GET" }),
    enabled,
    staleTime: 10 * 1000,
  });
}
