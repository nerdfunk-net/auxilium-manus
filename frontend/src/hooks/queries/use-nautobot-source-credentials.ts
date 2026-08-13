"use client";

import { useMemo } from "react";

import { buildSourceSettingKey } from "@/components/features/settings/constants/setting-keys";
import { useSettingQuery } from "@/hooks/queries/use-settings-query";

interface UseNautobotSourceCredentialsOptions {
  sourceId: string | undefined;
  enabled?: boolean;
}

export function useNautobotSourceCredentials({
  sourceId,
  enabled = true,
}: UseNautobotSourceCredentialsOptions) {
  const normalizedId = sourceId?.trim().toLowerCase() ?? "";
  const settingKey = normalizedId
    ? buildSourceSettingKey("nautobot", normalizedId)
    : "";

  const query = useSettingQuery({
    key: settingKey,
    enabled: enabled && Boolean(normalizedId),
  });

  const parsed = useMemo(() => {
    const value = query.data?.value;
    if (!value || typeof value !== "object") {
      return { url: "", tokenConfigured: false };
    }
    return {
      url: typeof value.url === "string" ? value.url : "",
      tokenConfigured: Boolean(value.token_configured),
    };
  }, [query.data?.value]);

  const isReady = Boolean(normalizedId && parsed.url && parsed.tokenConfigured);

  return {
    url: parsed.url,
    sourceId: normalizedId,
    tokenConfigured: parsed.tokenConfigured,
    isLoading: query.isLoading,
    isError: query.isError,
    isReady,
  };
}
