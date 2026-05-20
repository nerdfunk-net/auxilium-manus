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
  nautobot_url: string;
  nautobot_token: string;
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
  nautobot_url,
  nautobot_token,
  field,
  enabled = true,
}: UseFieldValuesOptions) {
  const { apiCall } = useApi();
  const hasCredentials = Boolean(nautobot_url && nautobot_token);

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.fieldValues(nautobot_url, field),
    queryFn: async () => {
      const params = new URLSearchParams({
        nautobot_url,
        nautobot_token,
      });
      const response = await apiCall<FieldValuesResponse>(
        `sources/nautobot/field-values/${encodeURIComponent(field)}?${params.toString()}`,
        { method: "GET" },
      );
      return {
        ...response,
        values: normalizeFieldValues(response.values ?? []),
      };
    },
    enabled: enabled && hasCredentials && Boolean(field),
    staleTime: 5 * 60 * 1000,
  });
}
