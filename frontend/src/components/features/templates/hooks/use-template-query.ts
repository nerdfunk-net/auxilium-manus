"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { Template } from "../types";

interface UseTemplateQueryOptions {
  templateId: number | null;
  enabled?: boolean;
}

export function useTemplateQuery({ templateId, enabled = true }: UseTemplateQueryOptions) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.templates.detail(templateId ?? 0),
    queryFn: () =>
      apiCall<Template>(`templates/${templateId}`, { method: "GET" }),
    enabled: enabled && templateId !== null,
    staleTime: 0,
  });
}
