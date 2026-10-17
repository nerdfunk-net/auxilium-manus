"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type { AttributePathResolveResponse } from "@/lib/attribute-path-types";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseAttributePathResolveQueryOptions {
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseAttributePathResolveQueryOptions = {};

/**
 * Resolves the currently-typed attribute path against a run's ancestor
 * devices, so the config panel can preview it live without opening the
 * picker. Debounced (300ms) the same way `useNetmikoDeviceSearchQuery` is,
 * since `path` tracks a live text input.
 */
export function useAttributePathResolveQuery(
  runId: number | null,
  ancestorNodeIds: string[],
  path: string,
  options: UseAttributePathResolveQueryOptions = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const [debouncedPath, setDebouncedPath] = useState(path);

  useEffect(() => {
    const timeout = setTimeout(() => setDebouncedPath(path), 300);
    return () => clearTimeout(timeout);
  }, [path]);

  const ancestorIdsKey = [...ancestorNodeIds].sort().join(",");
  const trimmedPath = debouncedPath.trim();

  return useQuery<AttributePathResolveResponse>({
    queryKey: runId
      ? queryKeys.attributePath.resolve(runId, ancestorIdsKey, trimmedPath)
      : queryKeys.attributePath.all,
    queryFn: () =>
      apiCall<AttributePathResolveResponse>(`runs/${runId}/resolve-attribute-path`, {
        method: "POST",
        body: JSON.stringify({ path: trimmedPath, ancestor_node_ids: ancestorNodeIds }),
      }),
    enabled: !!runId && trimmedPath.length > 0 && (options.enabled ?? true),
    staleTime: 5 * 1000,
  });
}
