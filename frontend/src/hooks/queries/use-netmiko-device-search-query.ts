"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { DeviceSummary } from "@/components/features/templates/types";

interface UseNetmikoDeviceSearchQueryOptions {
  sourceId: string;
  searchTerm: string;
  enabled: boolean;
}

export function useNetmikoDeviceSearchQuery({
  sourceId,
  searchTerm,
  enabled,
}: UseNetmikoDeviceSearchQueryOptions) {
  const { apiCall } = useApi();
  const [debouncedTerm, setDebouncedTerm] = useState(searchTerm);

  useEffect(() => {
    const timeout = setTimeout(() => setDebouncedTerm(searchTerm), 300);
    return () => clearTimeout(timeout);
  }, [searchTerm]);

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.deviceSearch(sourceId, debouncedTerm.trim()),
    queryFn: () =>
      apiCall<{ devices: DeviceSummary[] }>("sources/nautobot/devices/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_id: sourceId,
          search: debouncedTerm.trim(),
          limit: 20,
        }),
      }),
    enabled: enabled && debouncedTerm.trim().length >= 3,
    staleTime: 30 * 1000,
  });
}
