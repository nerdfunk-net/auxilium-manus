"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

/** Nautobot-shaped device produced by applying the step's device mapping. */
export interface GitDevicePreview {
  name: string;
  hostname?: string;
  serial?: string;
  asset_tag?: string;
  position?: string;
  face?: string;
  primary_ip4?: {
    address?: string;
    description?: string;
    dns_name?: string;
    status?: { name?: string };
  };
  role?: { name?: string };
  device_type?: { model?: string; manufacturer?: { name?: string } };
  platform?: { name?: string; network_driver?: string };
  location?: { name?: string; description?: string; parent?: { name?: string } };
  status?: { name?: string };
  interfaces?: {
    name?: string;
    description?: string;
    type?: string;
    mac_address?: string;
    mtu?: string;
    status?: { name?: string };
    ip_addresses?: { address?: string }[];
  }[];
  custom_fields?: Record<string, string>;
}

export interface GitPreviewResponse {
  devices: GitDevicePreview[];
  total_count: number;
  files_read: number;
  /** Every key / dot-path seen in the raw file entries (mapping suggestions). */
  available_keys: string[];
  /** Problems found while reading files (wrong shape, skipped entries, no files). */
  warnings: string[];
}

interface GitPreviewRequest {
  git_repository_id: number;
  filename_pattern: string;
  directory: string;
  device_mapping?: { source: string; target: string }[];
  file_format?: "yaml" | "csv";
  csv_delimiter?: string;
  csv_multiline?: boolean;
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
