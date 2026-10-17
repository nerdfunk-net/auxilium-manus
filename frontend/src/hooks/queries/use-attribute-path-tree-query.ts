"use client";

import { useQuery } from "@tanstack/react-query";

import type { AttributePathTreeResponse } from "@/lib/attribute-path-types";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseAttributePathTreeQueryOptions {
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseAttributePathTreeQueryOptions = {};

/** Discovers browsable attribute paths from a run's ancestor step results. */
export function useAttributePathTreeQuery(
  runId: number | null,
  ancestorNodeIds: string[],
  options: UseAttributePathTreeQueryOptions = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const ancestorIdsKey = [...ancestorNodeIds].sort().join(",");

  return useQuery<AttributePathTreeResponse>({
    queryKey: runId
      ? queryKeys.attributePath.tree(runId, ancestorIdsKey)
      : queryKeys.attributePath.all,
    queryFn: () => {
      const params = new URLSearchParams();
      for (const id of ancestorNodeIds) {
        params.append("ancestor_node_id", id);
      }
      return apiCall<AttributePathTreeResponse>(
        `runs/${runId}/attribute-tree?${params.toString()}`,
        { method: "GET" },
      );
    },
    enabled: !!runId && (options.enabled ?? true),
    staleTime: 30 * 1000,
  });
}
