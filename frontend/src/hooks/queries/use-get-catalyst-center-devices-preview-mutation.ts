"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

export const CATALYST_CENTER_PREVIEW_LIMIT = 25;

export interface CatalystCenterDevicePreview {
  id: string;
  hostname: string | null;
  management_ip: string | null;
  family: string | null;
  role: string | null;
  software_type: string | null;
  software_version: string | null;
  platform_id: string | null;
  reachability_status: string | null;
}

export interface CatalystCenterPreviewResponse {
  devices: CatalystCenterDevicePreview[];
  truncated: boolean;
}

export interface CatalystCenterPreviewRequest {
  source_id: string;
  filters: Record<string, string[] | string | boolean>;
  limit?: number;
}

/** Previews the first devices a step's filters would select (runs on the backend). */
export function useGetCatalystCenterDevicesPreviewMutation() {
  const { apiCall } = useApi();

  return useMutation({
    mutationFn: ({
      source_id: sourceId,
      filters,
      limit = CATALYST_CENTER_PREVIEW_LIMIT,
    }: CatalystCenterPreviewRequest) =>
      apiCall<CatalystCenterPreviewResponse>(
        `sources/catalyst_center/${encodeURIComponent(sourceId)}/devices/preview`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filters, limit }),
        },
      ),
  });
}
