import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { CustomField } from "@/components/features/inventory/types/device-selector";

interface UseInventoryCustomFieldsOptions {
  sourceId: string;
  enabled?: boolean;
}

export function useInventoryCustomFieldsQuery({
  sourceId,
  enabled = false,
}: UseInventoryCustomFieldsOptions) {
  const { apiCall } = useApi();
  const hasSource = Boolean(sourceId);

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.customFields(sourceId),
    queryFn: async () => {
      const params = new URLSearchParams({ source_id: sourceId });
      return apiCall<{ custom_fields: CustomField[] }>(
        `sources/nautobot/custom-fields?${params.toString()}`,
        { method: "GET" },
      );
    },
    enabled: enabled && hasSource,
    staleTime: 10 * 60 * 1000,
  });
}
