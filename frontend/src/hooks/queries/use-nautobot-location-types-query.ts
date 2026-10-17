import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface NautobotLocationType {
  id: string;
  name: string;
  display: string;
  parent_name: string | null;
  nestable: boolean;
}

interface NautobotLocationTypeListResponse {
  location_types: NautobotLocationType[];
}

interface UseNautobotLocationTypesOptions {
  sourceId: string;
  enabled?: boolean;
}

export function useNautobotLocationTypesQuery({
  sourceId,
  enabled = true,
}: UseNautobotLocationTypesOptions) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.locationTypes(sourceId),
    queryFn: async () => {
      const params = new URLSearchParams({ source_id: sourceId });
      const response = await apiCall<NautobotLocationTypeListResponse>(
        `sources/nautobot/location-types?${params.toString()}`,
        { method: "GET" },
      );
      return response.location_types;
    },
    enabled: enabled && Boolean(sourceId),
    staleTime: 5 * 60 * 1000,
  });
}
