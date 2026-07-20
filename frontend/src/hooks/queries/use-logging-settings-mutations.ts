"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export interface LoggingSettingsInput {
  default_log_level: string;
  workflow_log_enabled: boolean;
  workflow_log_level: string;
  workflow_log_max_bytes: number;
  workflow_log_backup_count: number;
  muted_loggers: Record<string, string>;
}

export function useLoggingSettingsMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const saveSettings = useMutation({
    mutationFn: (data: LoggingSettingsInput) =>
      apiCall("logging/settings", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.logging.settings() });
      toast({ title: "Saved", description: "Logging settings updated." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  return { saveSettings };
}
