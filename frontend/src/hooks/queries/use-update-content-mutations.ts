import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

import type { RegexFlags } from "@/components/features/workflow-steps/update-content/update-content-config";

export interface UpdateContentProbeResult {
  matched: boolean;
  match_count: number;
  updated_text: string | null;
}

interface ProbePayload {
  sample_text: string;
  pattern: string;
  replacement: string;
  regex_flags: RegexFlags;
  replace_all: boolean;
}

export function useUpdateContentProbeMutation() {
  const { apiCall } = useApi();
  return useMutation<UpdateContentProbeResult, Error, ProbePayload>({
    mutationFn: async (payload) =>
      apiCall<UpdateContentProbeResult>("workflow-steps/update-content/probe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
  });
}
