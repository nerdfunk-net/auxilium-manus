import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface FieldOption {
  value: string;
  label: string;
}

export interface FieldOptionsResponse {
  fields: FieldOption[];
  operators: FieldOption[];
}

export function useDeviceSelectionFieldOptionsQuery() {
  const { apiCall } = useApi();
  return useQuery<FieldOptionsResponse>({
    queryKey: queryKeys.deviceSelection.fieldOptions,
    queryFn: () =>
      apiCall("workflow-steps/device-selection/field-options", { method: "GET" }),
    staleTime: Infinity,
  });
}
