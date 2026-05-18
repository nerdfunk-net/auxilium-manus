import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface FieldValuesResponse {
  field: string;
  values: string[];
  input_type: string;
}

interface UseFieldValuesOptions {
  nautobot_url: string;
  nautobot_token: string;
  field: string;
  enabled?: boolean;
}

export function useDeviceSelectionFieldValuesQuery({
  nautobot_url,
  nautobot_token,
  field,
  enabled = true,
}: UseFieldValuesOptions) {
  const { apiCall } = useApi();
  const hasCredentials = Boolean(nautobot_url && nautobot_token);

  return useQuery<FieldValuesResponse>({
    queryKey: queryKeys.deviceSelection.fieldValues(field),
    queryFn: () =>
      apiCall("workflow-steps/device-selection/field-values", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nautobot_url, nautobot_token, field }),
      }),
    enabled: enabled && hasCredentials && Boolean(field),
    staleTime: 5 * 60 * 1000,
  });
}
