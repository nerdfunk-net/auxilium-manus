"use client";

import { useMutation } from "@tanstack/react-query";

import type { ActiveFilters } from "@/components/features/workflow-steps/get-aci-devices/filter-kinds";
import { useApi } from "@/hooks/use-api";

export const ACI_PREVIEW_LIMIT = 25;

export interface AciDevicePreview {
  node_id: number;
  name: string;
  role: "leaf" | "spine";
  pod_id: number | null;
  model: string | null;
  serial_number: string | null;
  software_version: string | null;
  fabric_state: string | null;
  management_ip: string | null;
}

export interface AciPreviewResponse {
  devices: AciDevicePreview[];
  truncated: boolean;
}

export interface AciPreviewRequest {
  source_id: string;
  filters: ActiveFilters;
  limit?: number;
}

/** Previews the first switches a step's filters would select (runs on the backend). */
export function useGetAciDevicesPreviewMutation() {
  const { apiCall } = useApi();

  return useMutation({
    mutationFn: ({
      source_id: sourceId,
      filters,
      limit = ACI_PREVIEW_LIMIT,
    }: AciPreviewRequest) =>
      apiCall<AciPreviewResponse>(
        `sources/aci/${encodeURIComponent(sourceId)}/devices/preview`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filters, limit }),
        },
      ),
  });
}
