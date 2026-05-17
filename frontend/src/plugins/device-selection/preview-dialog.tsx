"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

interface DeviceRow {
  name: string;
  site: string | null;
  role: string | null;
  status: string | null;
}

interface PreviewResponse {
  devices: DeviceRow[];
  total: number;
}

interface PreviewConfig {
  inventory_source: string;
  device_filter: Record<string, string>;
}

interface DeviceSelectionPreviewDialogProps {
  open: boolean;
  config: PreviewConfig;
  onClose: () => void;
}

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; data: PreviewResponse }
  | { status: "error"; message: string };

const IDLE: LoadState = { status: "idle" };

export function DeviceSelectionPreviewDialog({
  open,
  config,
  onClose,
}: DeviceSelectionPreviewDialogProps) {
  const [state, setState] = useState<LoadState>(IDLE);

  const fetchPreview = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const response = await fetch("/api/proxy/plugins/device-selection/preview", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          inventory_source: config.inventory_source,
          device_filter: config.device_filter,
        }),
      });

      if (!response.ok) {
        let message = `Request failed (${response.status})`;
        try {
          const body = (await response.json()) as { detail?: string };
          if (body.detail) message = body.detail;
        } catch {
          // ignore parse error — use status message
        }
        setState({ status: "error", message });
        return;
      }

      const data = (await response.json()) as PreviewResponse;
      setState({ status: "success", data });
    } catch {
      setState({
        status: "error",
        message:
          "Could not reach the backend. Make sure the server is running.",
      });
    }
  }, [config.inventory_source, config.device_filter]);

  useEffect(() => {
    if (open) {
      void fetchPreview();
    } else {
      setState(IDLE);
    }
  }, [open, fetchPreview]);

  if (!open) return null;

  return (
    <div
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div className="relative z-10 mx-4 flex w-full max-w-lg flex-col rounded-lg border bg-card shadow-lg">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <p className="text-sm font-semibold">Device Preview</p>
            <p className="text-xs text-muted-foreground">
              Devices from <span className="font-medium">{config.inventory_source || "—"}</span>{" "}
              matching current filter
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
          {state.status === "loading" && (
            <div className="space-y-2">
              {[...Array(4)].map((_, i) => (
                <div
                  className="h-8 animate-pulse rounded bg-muted"
                  key={i}
                />
              ))}
            </div>
          )}

          {state.status === "error" && (
            <div className="flex flex-col items-center gap-2 py-4 text-center">
              <p className="text-sm font-medium text-destructive">
                Preview unavailable
              </p>
              <p className="max-w-xs text-xs text-muted-foreground">
                {state.message}
              </p>
              <Button
                className="mt-2"
                onClick={() => void fetchPreview()}
                size="sm"
                variant="outline"
              >
                Retry
              </Button>
            </div>
          )}

          {state.status === "success" && state.data.total === 0 && (
            <p className="py-4 text-center text-xs text-muted-foreground">
              No devices matched the current filter.
            </p>
          )}

          {state.status === "success" && state.data.total > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                {state.data.total} device{state.data.total !== 1 ? "s" : ""} found
              </p>
              <div className="max-h-64 overflow-y-auto rounded border">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/80">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Name</th>
                      <th className="px-3 py-2 text-left font-medium">Site</th>
                      <th className="px-3 py-2 text-left font-medium">Role</th>
                      <th className="px-3 py-2 text-left font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.data.devices.map((device: DeviceRow) => (
                      <tr className="border-t" key={device.name}>
                        <td className="px-3 py-2 font-mono">{device.name}</td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {device.site ?? "—"}
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
