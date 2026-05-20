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

  const credentials = useMemo(() => {
    const value = query.data?.value;
    if (!value || typeof value !== "object") {
      return { url: "", token: "" };
    }
    return {
      url: typeof value.url === "string" ? value.url : "",
      token: typeof value.token === "string" ? value.token : "",
    };
  }, [query.data?.value]);

  const isReady = Boolean(
    normalizedId && credentials.url && credentials.token,
  );

  return {
    ...credentials,
    isLoading: query.isLoading,
    isError: query.isError,
    isReady,
    sourceId: normalizedId,
  };
}
