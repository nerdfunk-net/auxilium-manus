"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import type {
  MailSettings,
  MailSettingsResponse,
  MailTestResult,
} from "@/components/features/settings/types/mail";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useMailSettingsMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const saveSettings = useMutation({
    mutationFn: (data: MailSettings) =>
      apiCall<MailSettingsResponse>("mail/settings", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.mail.settings() });
      toast({ title: "Saved", description: "Mail settings updated." });
    },
    onError: (error: Error) =>
      toast({ title: "Error", description: error.message, variant: "destructive" }),
  });

  /** Connects and logs in with the SAVED settings; nothing is sent. */
  const testConnection = useMutation({
    mutationFn: () => apiCall<MailTestResult>("mail/settings/test", { method: "POST" }),
    onError: (error: Error) =>
      toast({ title: "Error", description: error.message, variant: "destructive" }),
  });

  return useMemo(() => ({ saveSettings, testConnection }), [saveSettings, testConnection]);
}
