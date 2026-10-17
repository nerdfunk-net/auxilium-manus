"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface WorkflowGalleryItem {
  id: string;
  name: string;
  description: string | null;
}

export interface WorkflowGalleryListResponse {
  items: WorkflowGalleryItem[];
}

interface UseWorkflowGalleryListQueryOptions {
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseWorkflowGalleryListQueryOptions = {};

export function useWorkflowGalleryListQuery(
  options: UseWorkflowGalleryListQueryOptions = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const { enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.workflows.gallery(),
    queryFn: async () =>
      apiCall<WorkflowGalleryListResponse>("workflows/gallery", { method: "GET" }),
    enabled,
    staleTime: 30 * 1000,
  });
}
