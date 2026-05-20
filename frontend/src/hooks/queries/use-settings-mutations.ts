"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  SettingCreatePayload,
  SettingRecord,
  SettingUpdatePayload,
} from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useSettingsMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidateSettings = (key?: string) => {
    queryClient.invalidateQueries({ queryKey: queryKeys.settings.all });
    if (key) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.settings.detail(key),
      });
    }
  };

  const createSetting = useMutation({
    mutationFn: (data: SettingCreatePayload) =>
      apiCall<SettingRecord>("settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (created) => {
      invalidateSettings(created.key);
      toast({ title: "Saved", description: "Setting created." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const updateSetting = useMutation({
    mutationFn: ({ key, data }: { key: string; data: SettingUpdatePayload }) =>
      apiCall<SettingRecord>(`settings/${encodeURIComponent(key)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (updated) => {
      invalidateSettings(updated.key);
      toast({ title: "Saved", description: "Setting updated." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const deleteSetting = useMutation({
    mutationFn: (key: string) =>
      apiCall<void>(`settings/${encodeURIComponent(key)}`, {
        method: "DELETE",
      }),
    onSuccess: (_result, key) => {
      invalidateSettings(key);
      toast({ title: "Removed", description: "Setting deleted." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const upsertSetting = useMutation({
    mutationFn: async ({
      key,
      value,
      description,
      exists,
    }: {
      key: string;
      value: Record<string, unknown>;
      description?: string;
      exists: boolean;
    }) => {
      if (exists) {
        return apiCall<SettingRecord>(`settings/${encodeURIComponent(key)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value, description }),
        });
      }
      return apiCall<SettingRecord>("settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value, description }),
      });
    },
    onSuccess: (saved) => {
      invalidateSettings(saved.key);
      toast({ title: "Saved", description: "Configuration saved." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  return { createSetting, updateSetting, deleteSetting, upsertSetting };
}
