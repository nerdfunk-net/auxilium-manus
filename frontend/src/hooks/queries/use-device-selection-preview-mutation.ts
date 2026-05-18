import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

export interface LogicalConditionPayload {
  field: string;
  operator: string;
  value: string;
}

export interface LogicalOperationPayload {
  operation_type: string;
  conditions: LogicalConditionPayload[];
  nested_operations: LogicalOperationPayload[];
}

export interface DevicePreview {
  id: string;
  name: string | null;
  serial: string | null;
  location: string | null;
  role: string | null;
  tags: string[];
  device_type: string | null;
  manufacturer: string | null;
  platform: string | null;
  primary_ip4: string | null;
  status: string | null;
}

export interface PreviewResponse {
  devices: DevicePreview[];
  total: number;
}

interface PreviewRequest {
  nautobot_url: string;
  nautobot_token: string;
  operations: LogicalOperationPayload[];
}

export function useDeviceSelectionPreviewMutation() {
  const { apiCall } = useApi();
  return useMutation<PreviewResponse, Error, PreviewRequest>({
    mutationFn: (data) =>
      apiCall("workflow-steps/device-selection/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
  });
}
