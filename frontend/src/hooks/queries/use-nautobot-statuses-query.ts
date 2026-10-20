import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface NautobotStatus {
  id: string;
  name: string;
}

interface NautobotStatusListResponse {
  statuses: NautobotStatus[];
}

/** Object types whose statuses the backend lists (see services/nautobot/statuses.py). */
export type NautobotStatusContentType = "ipam.ipaddress" | "ipam.prefix";

interface UseNautobotStatusesOptions {
  sourceId: string;
  contentType: NautobotStatusContentType;
  enabled?: boolean;
}

export function useNautobotStatusesQuery({
  sourceId,
  contentType,
  enabled = true,
}: UseNautobotStatusesOptions) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.statuses(sourceId, contentType),
    queryFn: async () => {
      const params = new URLSearchParams({ source_id: sourceId, content_type: contentType });
      const response = await apiCall<NautobotStatusListResponse>(
        `sources/nautobot/statuses?${params.toString()}`,
        { method: "GET" },
      );
      return response.statuses;
    },
    enabled: enabled && Boolean(sourceId),
    staleTime: 5 * 60 * 1000,
  });
}
