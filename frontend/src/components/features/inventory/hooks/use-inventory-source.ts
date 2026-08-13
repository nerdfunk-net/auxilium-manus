"use client";

import { useMemo } from "react";

import { SOURCE_KEY_PREFIXES } from "@/components/features/settings/constants/setting-keys";
import { groupSourceSettings } from "@/components/features/settings/utils/parse-source-settings";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";
import { useSettingsListQuery } from "@/hooks/queries/use-settings-query";

export function useInventorySource() {
  const { data, isLoading: isLoadingSettings } = useSettingsListQuery({
    keyPrefix: SOURCE_KEY_PREFIXES.nautobot,
  });

  const firstSourceId = useMemo(() => {
    const { nautobot } = groupSourceSettings(data?.settings ?? []);
    return nautobot[0]?.sourceId ?? "";
  }, [data?.settings]);

  const credentials = useNautobotSourceCredentials({
    sourceId: firstSourceId || undefined,
    enabled: Boolean(firstSourceId),
  });

  return useMemo(
    () => ({
      sourceId: firstSourceId,
      nautobotUrl: credentials.url,
      isLoading: isLoadingSettings || credentials.isLoading,
      isReady: Boolean(firstSourceId) && credentials.isReady,
      hasSources: Boolean(firstSourceId),
    }),
    [
      firstSourceId,
      credentials.url,
      credentials.isLoading,
      credentials.isReady,
      isLoadingSettings,
    ],
  );
}
