"use client";

import { useMemo } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { NAUTOBOT_TARGETS, targetLabel } from "./constants/nautobot-targets";
import type { GitDevicePreview } from "@/hooks/queries/use-get-git-devices-preview-mutation";
import { useGitRepositoryLabel } from "@/components/features/workflow-steps/shared/git-repository-value";

function valueAtPath(device: GitDevicePreview, path: string): string | undefined {
  let current: unknown = device;
  for (const part of path.split(".")) {
    if (typeof current !== "object" || current === null) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[part];
  }
  return typeof current === "string" ? current : undefined;
}

interface GitDevicesPreviewDialogProps {
  open: boolean;
  onClose: () => void;
  devices: GitDevicePreview[];
  warnings: string[];
  repositoryId: number | null;
}

export function GitDevicesPreviewDialog({
  open,
  onClose,
  devices,
  warnings,
  repositoryId,
}: GitDevicesPreviewDialogProps) {
  const repositoryLabel = useGitRepositoryLabel(repositoryId);

  // Only show attributes that at least one device actually has a value for.
  const columns = useMemo(
    () =>
      NAUTOBOT_TARGETS.map((target) => target.value).filter((path) =>
        devices.some((device) => valueAtPath(device, path) !== undefined),
      ),
    [devices],
  );

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Device Preview</DialogTitle>
          <DialogDescription>
            {devices.length} device{devices.length !== 1 ? "s" : ""} found in
            repository{" "}
            <code className="rounded bg-muted px-1 font-mono text-xs">
              {repositoryLabel ?? repositoryId}
            </code>
          </DialogDescription>
        </DialogHeader>

        {warnings.length > 0 && (
          <ul className="list-disc space-y-1 rounded-md border border-destructive/40 bg-destructive/5 py-2 pl-6 pr-3 text-xs text-destructive">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        )}

        {devices.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No devices found matching the configured pattern.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-md border text-xs">
            <table className="w-full">
              <thead className="border-b bg-muted/50 text-left font-medium text-muted-foreground">
                <tr>
                  {columns.map((path) => (
                    <th key={path} className="whitespace-nowrap px-3 py-2">
                      {targetLabel(path)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y">
                {devices.map((device, index) => (
                  <tr key={index} className="hover:bg-muted/30">
                    {columns.map((path) => (
                      <td key={path} className="px-3 py-2 font-mono">
                        {valueAtPath(device, path) ?? "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
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
