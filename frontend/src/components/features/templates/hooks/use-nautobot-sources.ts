"use client";

import { useMemo } from "react";

import { useNautobotConfiguredSourcesQuery } from "@/hooks/queries/use-nautobot-configured-sources-query";

/** List the configured Nautobot sources (used to populate the source selector). */
interface UseNautobotSourcesOptions {
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseNautobotSourcesOptions = {};

export function useNautobotSources(options: UseNautobotSourcesOptions = DEFAULT_OPTIONS) {
  const { enabled = true } = options;
  const { data, isLoading, isError } = useNautobotConfiguredSourcesQuery({ enabled });

  const sources = useMemo(
    () => (data ?? []).map((source) => ({ sourceId: source.source_id })),
    [data],
  );

  return useMemo(
    () => ({ sources, isLoading, isError }),
    [sources, isLoading, isError],
  );
}
