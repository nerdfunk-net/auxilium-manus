import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { CustomField } from "@/components/features/inventory/types/device-selector";

interface UseInventoryCustomFieldsOptions {
  nautobot_url: string;
  nautobot_token: string;
  enabled?: boolean;
}

export function useInventoryCustomFieldsQuery({
  nautobot_url,
  nautobot_token,
  enabled = false,
}: UseInventoryCustomFieldsOptions) {
  const { apiCall } = useApi();
  const hasCredentials = Boolean(nautobot_url && nautobot_token);

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.customFields(nautobot_url),
    queryFn: async () => {
      const params = new URLSearchParams({
        nautobot_url,
        nautobot_token,
      });
      return apiCall<{ custom_fields: CustomField[] }>(
        `sources/nautobot/custom-fields?${params.toString()}`,
        { method: "GET" },
      );
    },
    enabled: enabled && hasCredentials,
    staleTime: 10 * 60 * 1000,
  });
}
