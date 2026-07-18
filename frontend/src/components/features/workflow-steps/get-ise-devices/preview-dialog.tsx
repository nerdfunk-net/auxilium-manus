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

import type { IseDevicePreview } from "@/hooks/queries/use-get-ise-devices-preview-mutation";

interface IseDevicesPreviewDialogProps {
  open: boolean;
  onClose: () => void;
  devices: IseDevicePreview[];
  truncated: boolean;
  sourceId: string;
}

export function IseDevicesPreviewDialog({
  open,
  onClose,
  devices,
  truncated,
  sourceId,
}: IseDevicesPreviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Device Preview</DialogTitle>
          <DialogDescription>
            {devices.length} device{devices.length !== 1 ? "s" : ""} found in
            source{" "}
            <code className="rounded bg-muted px-1 font-mono text-xs">
              {sourceId}
            </code>
            {truncated && " — preview scanned a subset of ISE's devices; the actual run may find more"}
          </DialogDescription>
        </DialogHeader>

        {devices.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No devices found matching the configured lookup.
          </p>
        ) : (
          <div className="overflow-hidden rounded-md border text-xs">
            <div className="grid grid-cols-4 border-b bg-muted/50 px-3 py-2 font-medium text-muted-foreground">
              <span>Name</span>
              <span>IP Address</span>
              <span>Netmask</span>
              <span>Type</span>
            </div>
            <div className="divide-y">
              {devices.map((device) => (
                <div
                  key={device.id}
                  className="grid grid-cols-4 items-center px-3 py-2 hover:bg-muted/30"
                >
                  <span className="font-mono">{device.name}</span>
                  <span className="font-mono text-muted-foreground">
                    {device.primary_ip4 ?? "—"}
                  </span>
                  <span className="font-mono text-muted-foreground">
                    {device.mask !== null ? `/${device.mask}` : "—"}
                  </span>
                  <span>
                    {device.is_group_or_prefix ? (
                      <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                        group/prefix
                      </Badge>
                    ) : (
                      <Badge className="h-4 rounded px-1 text-[10px]" variant="outline">
                        device
                      </Badge>
                    )}
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
