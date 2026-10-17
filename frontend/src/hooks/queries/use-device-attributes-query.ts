"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseDeviceAttributesQueryOptions {
  deviceId: string | null;
  sourceId: string;
  attributes: string[];
  enabled?: boolean;
}

export function useDeviceAttributesQuery({
  deviceId,
  sourceId,
  attributes,
  enabled = true,
}: UseDeviceAttributesQueryOptions) {
  const { apiCall } = useApi();
  const attributesKey = [...attributes].sort().join(",");

  return useQuery({
    queryKey: queryKeys.templates.deviceAttributes(deviceId ?? "", attributesKey),
    queryFn: () =>
      apiCall<Record<string, unknown>>("sources/nautobot/devices/attributes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_id: sourceId,
          device_id: deviceId,
          list_of_attributes: attributes,
        }),
      }),
    enabled: enabled && deviceId != null,
    staleTime: 30 * 1000,
  });
}
