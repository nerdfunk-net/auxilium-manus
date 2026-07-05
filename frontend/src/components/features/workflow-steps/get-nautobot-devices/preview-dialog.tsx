"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  treeToOperations,
} from "@/components/features/workflow-steps/get-nautobot-devices/condition-builder/tree-to-operation";
import type { FilterTree } from "@/components/features/workflow-steps/get-nautobot-devices/condition-builder/types";
import { useApi } from "@/hooks/use-api";
import type { DevicePreview } from "@/hooks/queries/use-get-nautobot-devices-preview-mutation";
import { queryKeys } from "@/lib/query-keys";

interface PreviewConfig {
  nautobot_url: string;
  nautobot_token: string;
  device_filter: FilterTree;
}

interface PreviewDialogProps {
  open: boolean;
  config: PreviewConfig;
  inventoryName?: string | null;
  onClose: () => void;
}

interface PreviewApiResponse {
  devices: DevicePreview[];
  total_count: number;
}

async function fetchDevicePreview(
  apiCall: ReturnType<typeof useApi>["apiCall"],
  config: PreviewConfig,
): Promise<{ devices: DevicePreview[]; total: number }> {
  const operations = treeToOperations(config.device_filter);
  const response = await apiCall<PreviewApiResponse>("sources/nautobot/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      nautobot_url: config.nautobot_url,
      nautobot_token: config.nautobot_token,
      operations,
    }),
  });
  return { devices: response.devices, total: response.total_count };
}

export function DeviceSelectionPreviewDialog({
  open,
  config,
  inventoryName,
  onClose,
}: PreviewDialogProps) {
  const { apiCall } = useApi();
  const operationsKey = useMemo(
    () => JSON.stringify(treeToOperations(config.device_filter)),
    [config.device_filter],
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: queryKeys.sourcesNautobot.preview(config.nautobot_url, operationsKey),
    queryFn: () => fetchDevicePreview(apiCall, config),
    enabled: open && Boolean(config.nautobot_url && config.nautobot_token),
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });

  if (!open) return null;

  return (
    <div
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
    >
      <div aria-hidden="true" className="absolute inset-0 bg-black/50" onClick={onClose} />

      <div className="relative z-10 mx-4 flex w-full max-w-lg flex-col rounded-lg border bg-card shadow-lg">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <p className="text-sm font-semibold">Device Preview</p>
            <p className="text-xs text-muted-foreground">
              {inventoryName ? (
                <>
                  Devices from{" "}
                  <span className="font-medium">&ldquo;{inventoryName}&rdquo;</span> via{" "}
                  <span className="font-medium">{config.nautobot_url || "—"}</span>
                </>
              ) : (
                <>
                  Devices from{" "}
                  <span className="font-medium">{config.nautobot_url || "—"}</span> matching
                  selected inventory
                </>
              )}
            </p>
          </div>
          <Button
            aria-label="Close preview"
            className="h-7 w-7 p-0"
            onClick={onClose}
            size="sm"
            variant="ghost"
          >
            ×
          </Button>
        </div>

        <div className="min-h-[160px] p-4">
          {isLoading && (
            <div className="space-y-2">
              {[...Array(4)].map((_, index) => (
                <div className="h-8 animate-pulse rounded bg-muted" key={index} />
              ))}
            </div>
          )}

          {isError && (
            <div className="flex flex-col items-center gap-2 py-4 text-center">
              <p className="text-sm font-medium text-destructive">Preview unavailable</p>
              <p className="max-w-xs text-xs text-muted-foreground">
                {error instanceof Error
                  ? error.message
                  : "Could not reach the backend. Make sure the server is running."}
              </p>
              <Button className="mt-2" onClick={() => void refetch()} size="sm" variant="outline">
                Retry
              </Button>
            </div>
          )}

          {data && data.total === 0 && (
            <p className="py-4 text-center text-xs text-muted-foreground">
              No devices matched the selected inventory.
            </p>
          )}

          {data && data.total > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                {data.total} device{data.total !== 1 ? "s" : ""} found
              </p>
              <div className="max-h-64 overflow-y-auto rounded border">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/80">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Name</th>
                      <th className="px-3 py-2 text-left font-medium">Location</th>
                      <th className="px-3 py-2 text-left font-medium">Role</th>
                      <th className="px-3 py-2 text-left font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.devices.map((device) => (
                      <tr className="border-t" key={device.id}>
                        <td className="px-3 py-2 font-mono">{device.name ?? "—"}</td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {device.location ?? "—"}
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {device.role ?? "—"}
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {device.status ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end border-t px-4 py-3">
          <Button onClick={onClose} size="sm" variant="outline">
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}
