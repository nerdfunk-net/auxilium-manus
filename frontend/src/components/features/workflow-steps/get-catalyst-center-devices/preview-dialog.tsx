"use client";

import { Badge } from "@/components/ui/badge";
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
  CATALYST_CENTER_PREVIEW_LIMIT,
  type CatalystCenterDevicePreview,
} from "@/hooks/queries/use-get-catalyst-center-devices-preview-mutation";

interface CatalystCenterDevicesPreviewDialogProps {
  open: boolean;
  onClose: () => void;
  devices: CatalystCenterDevicePreview[];
  truncated: boolean;
  sourceId: string;
}

export function CatalystCenterDevicesPreviewDialog({
  open,
  onClose,
  devices,
  truncated,
  sourceId,
}: CatalystCenterDevicesPreviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Device Preview</DialogTitle>
          <DialogDescription>
            {truncated
              ? `Showing the first ${devices.length} devices`
              : `${devices.length} device${devices.length !== 1 ? "s" : ""} found`}{" "}
            in source{" "}
            <code className="rounded bg-muted px-1 font-mono text-xs">
              {sourceId}
            </code>
            {truncated &&
              ` — more devices match; the preview is limited to ${CATALYST_CENTER_PREVIEW_LIMIT}. The run selects all of them.`}
          </DialogDescription>
        </DialogHeader>

        {devices.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No devices match the configured filters.
          </p>
        ) : (
          <div className="overflow-hidden rounded-md border text-xs">
            <div className="grid grid-cols-5 border-b bg-muted/50 px-3 py-2 font-medium text-muted-foreground">
              <span>Name</span>
              <span>Management IP</span>
              <span>Family / Role</span>
              <span>Software</span>
              <span>Reachability</span>
            </div>
            <div className="divide-y">
              {devices.map((device) => (
                <div
                  key={device.id}
                  className="grid grid-cols-5 items-center px-3 py-2 hover:bg-muted/30"
                >
                  <span className="font-mono">{device.hostname ?? "—"}</span>
                  <span className="font-mono text-muted-foreground">
                    {device.management_ip ?? "—"}
                  </span>
                  <span className="text-muted-foreground">
                    {[device.family, device.role].filter(Boolean).join(" · ") || "—"}
                  </span>
                  <span className="text-muted-foreground">
                    {[device.software_type, device.software_version]
                      .filter(Boolean)
                      .join(" ") || "—"}
                  </span>
                  <span>
                    <Badge
                      className="h-4 rounded px-1 text-[10px]"
                      variant={
                        device.reachability_status === "Reachable"
                          ? "secondary"
                          : "outline"
                      }
                    >
                      {device.reachability_status ?? "unknown"}
                    </Badge>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
