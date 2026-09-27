import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface NautobotJobVariable {
  name: string;
  type: string;
  label: string | null;
  help_text: string | null;
  default: unknown;
  required: boolean;
  min_length: number | null;
  max_length: number | null;
  min_value: number | null;
  max_value: number | null;
  choices: unknown;
  model: string | null;
}

interface NautobotJobVariablesResponse {
  variables: NautobotJobVariable[];
}

interface UseNautobotJobVariablesOptions {
  sourceId: string;
  jobId: string;
  enabled?: boolean;
}

export function useNautobotJobVariablesQuery({
  sourceId,
  jobId,
  enabled = true,
}: UseNautobotJobVariablesOptions) {
  const { apiCall } = useApi();
  const hasSource = Boolean(sourceId);
  const hasJob = Boolean(jobId);

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.jobVariables(sourceId, jobId),
    queryFn: async () => {
      const params = new URLSearchParams({ source_id: sourceId });
      const response = await apiCall<NautobotJobVariablesResponse>(
        `sources/nautobot/jobs/${encodeURIComponent(jobId)}/variables?${params.toString()}`,
        { method: "GET" },
      );
      return response.variables;
    },
    enabled: enabled && hasSource && hasJob,
    staleTime: 60 * 1000,
  });
}
