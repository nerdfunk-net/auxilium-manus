import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface NautobotJobSummary {
  id: string;
  name: string;
  module_name: string | null;
  grouping: string | null;
  enabled: boolean;
  description: string | null;
}

interface NautobotJobListResponse {
  jobs: NautobotJobSummary[];
}

interface UseNautobotJobsOptions {
  sourceId: string;
  enabledOnly?: boolean;
  enabled?: boolean;
}

export function useNautobotJobsQuery({
  sourceId,
  enabledOnly = true,
  enabled = true,
}: UseNautobotJobsOptions) {
  const { apiCall } = useApi();
  const hasSource = Boolean(sourceId);

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.jobs(sourceId, enabledOnly),
    queryFn: async () => {
      const params = new URLSearchParams({
        source_id: sourceId,
        enabled_only: String(enabledOnly),
      });
      const response = await apiCall<NautobotJobListResponse>(
        `sources/nautobot/jobs?${params.toString()}`,
        { method: "GET" },
      );
      return response.jobs;
    },
    enabled: enabled && hasSource,
    staleTime: 60 * 1000,
  });
}
