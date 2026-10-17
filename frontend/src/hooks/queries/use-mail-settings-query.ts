"use client";

import { useQuery } from "@tanstack/react-query";

import type { MailSettingsResponse } from "@/components/features/settings/types/mail";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useMailSettingsQuery() {
  const { apiCall } = useApi();
  return useQuery<MailSettingsResponse>({
    queryKey: queryKeys.mail.settings(),
    queryFn: () => apiCall<MailSettingsResponse>("mail/settings", { method: "GET" }),
    staleTime: 60 * 1000,
  });
}
