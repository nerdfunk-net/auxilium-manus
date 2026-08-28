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
  git_repository_id: number;
  filename_pattern: string;
  directory: string;
}

export function useGetGitDevicesPreviewMutation() {
  const { apiCall } = useApi();

  return useMutation({
    mutationFn: async (request: GitPreviewRequest) => {
      const { git_repository_id, ...body } = request;
      return apiCall<GitPreviewResponse>(`git/${git_repository_id}/preview-devices`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    },
  });
}
