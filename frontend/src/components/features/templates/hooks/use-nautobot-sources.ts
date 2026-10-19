"use client";

import { useMemo } from "react";

import { SOURCE_KEY_PREFIXES } from "@/components/features/settings/constants/setting-keys";
import { groupSourceSettings } from "@/components/features/settings/utils/parse-source-settings";
import { useSettingsListQuery } from "@/hooks/queries/use-settings-query";

/** List the configured Nautobot sources (used to populate the source selector). */
interface UseNautobotSourcesOptions {
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseNautobotSourcesOptions = {};

export function useNautobotSources(options: UseNautobotSourcesOptions = DEFAULT_OPTIONS) {
  const { enabled = true } = options;
  const { data, isLoading, isError } = useSettingsListQuery({
    keyPrefix: SOURCE_KEY_PREFIXES.nautobot,
    enabled,
  });

  const sources = useMemo(() => {
    const { nautobot } = groupSourceSettings(data?.settings ?? []);
    return nautobot.map((source) => ({ sourceId: source.sourceId }));
  }, [data?.settings]);

  return useMemo(
    () => ({ sources, isLoading, isError }),
    [sources, isLoading, isError],
  );
}
