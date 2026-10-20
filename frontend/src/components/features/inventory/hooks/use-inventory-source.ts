"use client";

import { useMemo } from "react";

import { useNautobotConfiguredSourcesQuery } from "@/hooks/queries/use-nautobot-configured-sources-query";

export function useInventorySource() {
  const { data, isLoading, error } = useNautobotConfiguredSourcesQuery();

  const source = data?.[0];
  const sourceId = source?.source_id ?? "";
  const url = source?.url ?? "";
  const tokenConfigured = Boolean(source?.token_configured);

  return useMemo(
    () => ({
      sourceId,
      nautobotUrl: url,
      isLoading,
      isReady: Boolean(sourceId && url && tokenConfigured),
      hasSources: Boolean(sourceId),
      error: error?.message ?? null,
    }),
    [sourceId, url, tokenConfigured, isLoading, error],
  );
}
