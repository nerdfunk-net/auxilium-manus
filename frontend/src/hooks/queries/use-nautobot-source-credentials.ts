"use client";

import { useMemo } from "react";

import { useNautobotConfiguredSourcesQuery } from "@/hooks/queries/use-nautobot-configured-sources-query";

interface UseNautobotSourceCredentialsOptions {
  sourceId: string | undefined;
  enabled?: boolean;
}

export function useNautobotSourceCredentials({
  sourceId,
  enabled = true,
}: UseNautobotSourceCredentialsOptions) {
  const normalizedId = sourceId?.trim().toLowerCase() ?? "";

  const query = useNautobotConfiguredSourcesQuery({
    enabled: enabled && Boolean(normalizedId),
  });

  const parsed = useMemo(() => {
    const source = query.data?.find((candidate) => candidate.source_id === normalizedId);
    return {
      url: source?.url ?? "",
      tokenConfigured: Boolean(source?.token_configured),
    };
  }, [query.data, normalizedId]);

  const isReady = Boolean(normalizedId && parsed.url && parsed.tokenConfigured);

  const { isLoading, isError } = query;

  return useMemo(
    () => ({
      url: parsed.url,
      sourceId: normalizedId,
      tokenConfigured: parsed.tokenConfigured,
      isLoading,
      isError,
      isReady,
    }),
    [parsed.url, normalizedId, parsed.tokenConfigured, isLoading, isError, isReady],
  );
}
