import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

import type { NautobotUuidResourceType } from "@/components/features/workflow-steps/shared/nautobot-field-rows";

export interface ResolveObjectRequest {
  source_id: string;
  resource_type: NautobotUuidResourceType;
  value: string;
  content_type?: string;
}

export interface ResolveObjectResponse {
  resolved: boolean;
  id: string | null;
}

export function useNautobotResolveObjectMutation() {
  const { apiCall } = useApi();
  return useMutation<ResolveObjectResponse, Error, ResolveObjectRequest>({
    mutationFn: async (data) =>
      apiCall<ResolveObjectResponse>("sources/nautobot/resolve-object", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
  });
}
