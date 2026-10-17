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
  logical_operations?: FieldOption[];
}

export function useGetNautobotDevicesFieldOptionsQuery() {
  const { apiCall } = useApi();
  return useQuery<FieldOptionsResponse>({
    queryKey: queryKeys.sourcesNautobot.fieldOptions(),
    queryFn: () => apiCall("sources/nautobot/field-options", { method: "GET" }),
    staleTime: Infinity,
  });
}
