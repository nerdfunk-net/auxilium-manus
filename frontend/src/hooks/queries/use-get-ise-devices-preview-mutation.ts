"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

const PREVIEW_LIMIT = 25;

export interface IseDevicePreview {
  id: string;
  name: string;
  primary_ip4: string | null;
  mask: number | null;
  is_group_or_prefix: boolean;
  groups: string[];
}

export interface IsePreviewResponse {
  devices: IseDevicePreview[];
  truncated: boolean;
}

export interface IsePreviewRequest {
  source_id: string;
  query_mode: "name" | "cidr" | "group";
  device_names?: string[];
  cidr?: string;
  group_name?: string;
}

interface IseNetworkDeviceIp {
  ipaddress?: string;
  mask?: number;
}

interface IseNetworkDevice {
  id?: string;
  name?: string;
  NetworkDeviceIPList?: IseNetworkDeviceIp[];
  NetworkDeviceGroupList?: string[];
}

interface IseListSummary {
  id?: string;
  name?: string;
}

interface IseListResponse {
  total: number;
  resources: IseListSummary[];
  next_page: string | null;
}

function toPreview(device: IseNetworkDevice): IseDevicePreview | null {
  if (!device.id || !device.name) return null;
  const ip = device.NetworkDeviceIPList?.[0];
  const mask = typeof ip?.mask === "number" ? ip.mask : null;
  return {
    id: device.id,
    name: device.name,
    primary_ip4: ip?.ipaddress ?? null,
    mask,
    is_group_or_prefix: mask !== null && mask !== 32,
    groups: device.NetworkDeviceGroupList ?? [],
  };
}

/** Returns true when `ip` (IPv4 dotted-quad) falls inside `cidr`. */
function ipv4InCidr(ip: string, cidr: string): boolean {
  const [network, prefixRaw] = cidr.split("/");
  const prefix = prefixRaw ? Number(prefixRaw) : 32;
  const toInt = (addr: string) =>
    addr
      .split(".")
      .map(Number)
      .reduce((acc, octet) => (acc << 8) + (octet & 255), 0) >>> 0;
  if (!network || Number.isNaN(prefix)) return false;
  const mask = prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0;
  try {
    return (toInt(ip) & mask) === (toInt(network) & mask);
  } catch {
    return false;
  }
}

export function useGetIseDevicesPreviewMutation() {
  const { apiCall } = useApi();

  const fetchDetail = async (
    sourceId: string,
    deviceId: string,
  ): Promise<IseNetworkDevice | null> => {
    try {
      const result = await apiCall<{ NetworkDevice: IseNetworkDevice }>(
        `sources/ise/${sourceId}/devices/${deviceId}`,
        { method: "GET" },
      );
      return result.NetworkDevice;
    } catch {
      return null;
    }
  };

  const fetchDetails = async (
    sourceId: string,
    summaries: IseListSummary[],
  ): Promise<IseNetworkDevice[]> => {
    const details: IseNetworkDevice[] = [];
    for (const summary of summaries.slice(0, PREVIEW_LIMIT)) {
      if (!summary.id) continue;
      const detail = await fetchDetail(sourceId, summary.id);
      if (detail) details.push(detail);
    }
    return details;
  };

  return useMutation({
    mutationFn: async (request: IsePreviewRequest): Promise<IsePreviewResponse> => {
      const { source_id: sourceId, query_mode: queryMode } = request;
      let rawDevices: IseNetworkDevice[] = [];
      let truncated = false;

      if (queryMode === "name") {
        const names = (request.device_names ?? []).slice(0, PREVIEW_LIMIT);
        for (const name of names) {
          try {
            const result = await apiCall<{ NetworkDevice: IseNetworkDevice }>(
              `sources/ise/${sourceId}/devices/name/${encodeURIComponent(name)}`,
              { method: "GET" },
            );
            rawDevices.push(result.NetworkDevice);
          } catch {
            // device not found in ISE — skip, matches executor behavior
          }
        }
      } else if (queryMode === "group") {
        const groupName = request.group_name ?? "";
        const result = await apiCall<IseListResponse>(
          `sources/ise/${sourceId}/devices/ndg/${encodeURIComponent(groupName)}?page=1&size=${PREVIEW_LIMIT}`,
          { method: "GET" },
        );
        truncated = result.total > result.resources.length;
        rawDevices = await fetchDetails(sourceId, result.resources);
      } else if (queryMode === "cidr") {
        const cidr = (request.cidr ?? "").trim();
        const isHost = !cidr.includes("/") || cidr.endsWith("/32");
        const host = cidr.split("/")[0];

        if (isHost) {
          const result = await apiCall<IseListResponse>(
            `sources/ise/${sourceId}/devices?filter=${encodeURIComponent(`ipaddress.EQ.${host}`)}`,
            { method: "GET" },
          );
          rawDevices = await fetchDetails(sourceId, result.resources);
        } else {
          const result = await apiCall<IseListResponse>(
            `sources/ise/${sourceId}/devices?page=1&size=${PREVIEW_LIMIT}`,
            { method: "GET" },
          );
          truncated = result.total > result.resources.length;
          const details = await fetchDetails(sourceId, result.resources);
          rawDevices = details.filter((detail) =>
            (detail.NetworkDeviceIPList ?? []).some(
              (entry) => entry.ipaddress && ipv4InCidr(entry.ipaddress, cidr),
            ),
          );
        }
      }

      const devices = rawDevices
        .map(toPreview)
        .filter((device): device is IseDevicePreview => device !== null);

      return { devices, truncated };
    },
  });
}
