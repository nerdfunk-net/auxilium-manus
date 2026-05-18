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

export function useGetNautobotDevicesFieldOptionsQuery() {
  const { apiCall } = useApi();
  return useQuery<FieldOptionsResponse>({
    queryKey: queryKeys.getNautobotDevices.fieldOptions,
    queryFn: () =>
      apiCall("workflow-steps/get-nautobot-devices/field-options", { method: "GET" }),
    staleTime: Infinity,
  });
}
