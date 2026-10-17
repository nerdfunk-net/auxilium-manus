"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { TemplateListResponse } from "../types";

interface UseTemplatesQueryOptions {
  search?: string;
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseTemplatesQueryOptions = {};

export function useTemplatesQuery(options: UseTemplatesQueryOptions = DEFAULT_OPTIONS) {
  const { apiCall } = useApi();
  const { search, enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.templates.list(search || undefined),
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) {
        params.set("search", search);
      }
      const query = params.toString();
      return apiCall<TemplateListResponse>(
        `templates${query ? `?${query}` : ""}`,
        { method: "GET" },
      );
    },
    enabled,
    staleTime: 30 * 1000,
  });
}
