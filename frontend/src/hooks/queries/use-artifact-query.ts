"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";
import type { ArtifactRef } from "@/lib/workflow-context-types";

export interface ArtifactContentResponse {
  artifact_id: string;
  kind: string;
  media_type: string;
  size_bytes: number | null;
  content: string;
}

interface UseArtifactQueryOptions {
  runId: number | null;
  artifactRef: ArtifactRef | null;
  enabled?: boolean;
}

export function useArtifactQuery({
  runId,
  artifactRef,
  enabled = true,
}: UseArtifactQueryOptions) {
  const { apiCall } = useApi();
  const artifactId = artifactRef?.artifact_id ?? null;

  return useQuery({
    queryKey: queryKeys.workflowRuns.artifact(runId ?? 0, artifactId ?? ""),
    queryFn: () =>
      apiCall<ArtifactContentResponse>(`runs/${runId}/artifacts/${artifactId}`, {
        method: "GET",
      }),
    enabled: enabled && runId != null && artifactId != null,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}
