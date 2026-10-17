import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface FieldValueOption {
  value: string;
  label: string;
}

export interface FieldValuesResponse {
  field: string;
  values: string[] | FieldValueOption[];
  input_type: string;
}

interface UseFieldValuesOptions {
  sourceId: string;
  field: string;
  enabled?: boolean;
}

function normalizeFieldValues(
  values: string[] | FieldValueOption[],
): FieldValueOption[] {
  if (values.length === 0) {
    return [];
  }
  if (typeof values[0] === "string") {
    return (values as string[]).map((value) => ({ value, label: value }));
  }
  return values as FieldValueOption[];
}

export function useGetNautobotDevicesFieldValuesQuery({
  sourceId,
  field,
  enabled = true,
}: UseFieldValuesOptions) {
  const { apiCall } = useApi();
  const hasSource = Boolean(sourceId);

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.fieldValues(sourceId, field),
    queryFn: async () => {
      const params = new URLSearchParams({ source_id: sourceId });
      const response = await apiCall<FieldValuesResponse>(
        `sources/nautobot/field-values/${encodeURIComponent(field)}?${params.toString()}`,
        { method: "GET" },
      );
      return {
        ...response,
        values: normalizeFieldValues(response.values ?? []),
      };
    },
    enabled: enabled && hasSource && Boolean(field),
    staleTime: 5 * 60 * 1000,
  });
}
