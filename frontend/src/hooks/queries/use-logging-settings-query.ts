"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface LoggingSettingsData {
  default_log_level: string;
  workflow_log_enabled: boolean;
  workflow_log_level: string;
  workflow_log_max_bytes: number;
  workflow_log_backup_count: number;
  muted_loggers: Record<string, string>;
  log_directory: string;
  app_log_file: string;
  worker_log_file: string;
  workflow_log_file: string;
}

export function useLoggingSettingsQuery() {
  const { apiCall } = useApi();
  return useQuery<LoggingSettingsData>({
    queryKey: queryKeys.logging.settings(),
    queryFn: () => apiCall("logging/settings", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
