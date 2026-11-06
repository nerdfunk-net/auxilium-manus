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
  ACI_PREVIEW_LIMIT,
  type AciDevicePreview,
} from "@/hooks/queries/use-get-aci-devices-preview-mutation";

interface AciDevicesPreviewDialogProps {
  open: boolean;
  onClose: () => void;
  devices: AciDevicePreview[];
  truncated: boolean;
  sourceId: string;
}

export function AciDevicesPreviewDialog({
  open,
  onClose,
  devices,
  truncated,
  sourceId,
}: AciDevicesPreviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Switch Preview</DialogTitle>
          <DialogDescription>
            {truncated
              ? `Showing the first ${devices.length} switches`
              : `${devices.length} switch${devices.length !== 1 ? "es" : ""} found`}{" "}
            in source{" "}
            <code className="rounded bg-muted px-1 font-mono text-xs">
              {sourceId}
            </code>
            {truncated &&
              ` — more switches match; the preview is limited to ${ACI_PREVIEW_LIMIT}. The run selects all of them.`}
          </DialogDescription>
        </DialogHeader>

        {devices.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No switches match the configured filters.
          </p>
        ) : (
          <div className="overflow-hidden rounded-md border text-xs">
            <div className="grid grid-cols-6 border-b bg-muted/50 px-3 py-2 font-medium text-muted-foreground">
              <span>Name</span>
              <span>Node / Pod</span>
              <span>Role / Model</span>
              <span>Software</span>
              <span>Management IP</span>
              <span>Fabric state</span>
            </div>
            <div className="divide-y">
              {devices.map((device) => (
                <div
                  key={device.node_id}
                  className="grid grid-cols-6 items-center px-3 py-2 hover:bg-muted/30"
                >
                  <span className="font-mono">{device.name}</span>
                  <span className="font-mono text-muted-foreground">
                    {device.node_id}
                    {device.pod_id !== null ? ` / pod ${device.pod_id}` : ""}
                  </span>
                  <span className="text-muted-foreground">
                    {[device.role, device.model].filter(Boolean).join(" · ")}
                  </span>
                  <span className="text-muted-foreground">
                    {device.software_version ?? "—"}
                  </span>
                  <span className="font-mono text-muted-foreground">
                    {device.management_ip ?? "none configured"}
                  </span>
                  <span>
                    <Badge
                      className="h-4 rounded px-1 text-[10px]"
                      variant={
                        device.fabric_state === "active" ? "secondary" : "outline"
                      }
                    >
                      {device.fabric_state ?? "unknown"}
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
