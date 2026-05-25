"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

export interface GitDevicePreview {
  id: null;
  name: string;
  primary_ip4: { address: string } | null;
  platform: {
    name: null;
    manufacturer: null;
    network_driver: string | null;
  };
}

export interface GitPreviewResponse {
  devices: GitDevicePreview[];
  total_count: number;
  files_read: number;
}

interface GitPreviewRequest {
  git_source_id: string;
  filename_pattern: string;
}

export function useGetGitDevicesPreviewMutation() {
  const { apiCall } = useApi();

  return useMutation({
    mutationFn: async (request: GitPreviewRequest) => {
      console.debug("[DEBUG] useGetGitDevicesPreviewMutation — fetch START", request);
      const result = await apiCall<GitPreviewResponse>("sources/git/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      console.debug("[DEBUG] useGetGitDevicesPreviewMutation — fetch DONE", result);
      return result;
    },
    onSuccess: (data) => {
      console.debug("[DEBUG] useGetGitDevicesPreviewMutation — onSuccess", data);
    },
    onError: (error) => {
      console.debug("[DEBUG] useGetGitDevicesPreviewMutation — onError", error);
    },
    onSettled: (data, error) => {
      console.debug("[DEBUG] useGetGitDevicesPreviewMutation — onSettled data=%o error=%o", data, error);
    },
  });
}
