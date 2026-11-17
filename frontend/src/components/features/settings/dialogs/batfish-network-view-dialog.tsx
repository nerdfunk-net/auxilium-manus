"use client";

import { Camera } from "lucide-react";
import { useState } from "react";

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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useBatfishSnapshotDevicesQuery } from "@/hooks/queries/use-batfish-snapshot-devices-query";
import { useBatfishSnapshotsQuery } from "@/hooks/queries/use-batfish-snapshots-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";
import { cn } from "@/lib/utils";

import { snapshotLabel } from "../utils/format-snapshot-date";

interface BatfishNetworkViewDialogProps {
  sourceId: string;
  /** Network to show; null keeps the dialog closed. */
  network: string | null;
  onClose: () => void;
}

export function BatfishNetworkViewDialog({
  sourceId,
  network,
  onClose,
}: BatfishNetworkViewDialogProps) {
  const user = useAuthStore((state) => state.user);
  const canQuery = hasPermission(user, "sources.batfish", "query");
  const open = network !== null;
  const snapshotsQuery = useBatfishSnapshotsQuery(sourceId, network ?? "");
  const snapshots = snapshotsQuery.data?.snapshots;
  // The choice is remembered with its network, so another network falls back to the default.
  const [selection, setSelection] = useState<{ network: string; name: string } | null>(null);
  const selected = selection?.network === network ? selection.name : null;
  // Default: the newest snapshot (the list is newest first).
  const activeSnapshot = selected ?? snapshots?.[0]?.name ?? "";

  const devicesQuery = useBatfishSnapshotDevicesQuery(
    sourceId,
    network ?? "",
    activeSnapshot,
    open && canQuery,
  );

  return (
    <Dialog open={open} onOpenChange={(next: boolean) => !next && onClose()}>
      <DialogContent className="flex h-[85vh] max-w-4xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="sr-only">
          <DialogTitle>Network {network}</DialogTitle>
          <DialogDescription>
            Snapshots of the network and the devices of the selected snapshot.
          </DialogDescription>
        </DialogHeader>
        <div className="step-header px-4 py-2.5 text-sm font-semibold">
          Network: <span className="font-mono">{network}</span>
        </div>

        <div className="flex min-h-0 flex-1">
          <nav
            aria-label="Snapshots"
            className="w-72 shrink-0 overflow-y-auto border-r border-border bg-card"
          >
            <p className="border-b border-border px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Snapshots
            </p>
            {snapshotsQuery.isLoading ? (
              <p className="px-3 py-2 text-xs text-muted-foreground">Loading…</p>
            ) : snapshots?.length ? (
              <ul>
                {snapshots.map((snap) => (
                  <li key={snap.name}>
                    <button
                      type="button"
                      onClick={() => setSelection({ network: network ?? "", name: snap.name })}
                      className={cn(
                        "flex w-full items-start gap-2 px-3 py-2 text-left text-xs hover:bg-muted",
                        snap.name === activeSnapshot &&
                          "bg-step-surface text-step-surface-foreground hover:bg-step-surface",
                      )}
                    >
                      <Camera className="mt-0.5 size-3.5 shrink-0 text-step" aria-hidden />
                      <span className="break-all">
                        {snapshotLabel(snap.name, snap.created_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-3 py-2 text-xs text-muted-foreground">
                This network has no snapshots.
              </p>
            )}
          </nav>

          <div className="min-w-0 flex-1 overflow-y-auto bg-muted p-4">
            {!canQuery ? (
              <p className="text-xs text-muted-foreground">
                Showing devices needs the sources.batfish:query permission.
              </p>
            ) : !activeSnapshot ? null : devicesQuery.isLoading ? (
              <p className="text-xs text-muted-foreground">Loading devices…</p>
            ) : devicesQuery.isError ? (
              <p className="text-xs text-destructive">
                Could not load the devices: {devicesQuery.error.message}
              </p>
            ) : (
              <div className="space-y-2">
                {devicesQuery.data?.ips_unavailable ? (
                  <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
                    IP addresses could not be read for this snapshot.
                  </p>
                ) : null}
                {devicesQuery.data?.truncated ? (
                  <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
                    The list is cut off; not every device or address is shown.
                  </p>
                ) : null}
                <div className="rounded-lg border bg-card">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Device name</TableHead>
                        <TableHead>IP Address</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {devicesQuery.data?.devices.length ? (
                        devicesQuery.data.devices.map((device) => (
                          <TableRow key={device.device}>
                            <TableCell className="font-mono text-xs">
                              {device.device}
                            </TableCell>
                            <TableCell className="font-mono text-xs">
                              {device.ip_addresses.join(", ") || "—"}
                            </TableCell>
                          </TableRow>
                        ))
                      ) : (
                        <TableRow>
                          <TableCell
                            colSpan={2}
                            className="text-xs text-muted-foreground"
                          >
                            No devices in this snapshot.
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="shrink-0 border-t bg-card px-4 py-3">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
