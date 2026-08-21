"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  treeToOperations,
} from "@/components/features/workflow-steps/get-nautobot-devices/condition-builder/tree-to-operation";
import type { FilterTree } from "@/components/features/workflow-steps/get-nautobot-devices/condition-builder/types";
import { useApi } from "@/hooks/use-api";
import type { DevicePreview } from "@/hooks/queries/use-get-nautobot-devices-preview-mutation";
import { queryKeys } from "@/lib/query-keys";

interface PreviewConfig {
  source_id: string;
  inventory_type: "filter" | "static";
  device_filter: FilterTree;
  device_ids: string[];
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
  if (config.inventory_type === "static") {
    const response = await apiCall<PreviewApiResponse>("sources/nautobot/preview-device-ids", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_id: config.source_id,
        device_ids: config.device_ids,
      }),
    });
    return { devices: response.devices, total: response.total_count };
  }

  const operations = treeToOperations(config.device_filter);
  const response = await apiCall<PreviewApiResponse>("sources/nautobot/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_id: config.source_id,
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
    () =>
      config.inventory_type === "static"
        ? JSON.stringify({ static: config.device_ids })
        : JSON.stringify(treeToOperations(config.device_filter)),
    [config.inventory_type, config.device_filter, config.device_ids],
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: queryKeys.sourcesNautobot.preview(config.source_id, operationsKey),
    queryFn: () => fetchDevicePreview(apiCall, config),
    enabled: open && Boolean(config.source_id),
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Device Preview</DialogTitle>
          <DialogDescription>
            {inventoryName ? (
              <>
                Devices from{" "}
                <span className="font-medium">&ldquo;{inventoryName}&rdquo;</span> via{" "}
                <span className="font-medium">{config.source_id || "—"}</span>
              </>
            ) : (
              <>
                Devices from{" "}
                <span className="font-medium">{config.source_id || "—"}</span> matching
                selected inventory
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-[160px]">
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

        <DialogFooter>
          <Button onClick={onClose} size="sm" variant="outline">
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
