"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { GitDevicePreview } from "@/hooks/queries/use-get-git-devices-preview-mutation";

interface GitDevicesPreviewDialogProps {
  open: boolean;
  onClose: () => void;
  devices: GitDevicePreview[];
  sourceId: string;
}

export function GitDevicesPreviewDialog({
  open,
  onClose,
  devices,
  sourceId,
}: GitDevicesPreviewDialogProps) {
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
          </DialogDescription>
        </DialogHeader>

        {devices.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No devices found matching the configured pattern.
          </p>
        ) : (
          <div className="overflow-hidden rounded-md border text-xs">
            <div className="grid grid-cols-3 border-b bg-muted/50 px-3 py-2 font-medium text-muted-foreground">
              <span>Name</span>
              <span>IP Address</span>
              <span>Network Driver</span>
            </div>
            <div className="divide-y">
              {devices.map((device, index) => (
                <div
                  key={index}
                  className="grid grid-cols-3 px-3 py-2 hover:bg-muted/30"
                >
                  <span className="font-mono">{device.name}</span>
                  <span className="font-mono text-muted-foreground">
                    {device.primary_ip4?.address ?? "—"}
                  </span>
                  <span className="text-muted-foreground">
                    {device.platform?.network_driver ?? "—"}
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
