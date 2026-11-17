"use client";

import { Eye, Layers, Trash2 } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { useBatfishNetworkSummariesQuery } from "@/hooks/queries/use-batfish-network-summaries-query";
import { useBatfishSnapshotsQuery } from "@/hooks/queries/use-batfish-snapshots-query";
import { useBatfishSourcesMutations } from "@/hooks/queries/use-batfish-sources-mutations";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import {
  formatSnapshotDate,
  snapshotLabel,
} from "../utils/format-snapshot-date";
import { BatfishNetworkViewDialog } from "./batfish-network-view-dialog";

interface BatfishManageDialogProps {
  /** Source to manage; null keeps the dialog closed. */
  sourceId: string | null;
  onClose: () => void;
}

type Pending =
  | { kind: "networks"; networks: string[] }
  | { kind: "snapshots"; network: string; snapshots: string[] };

/** Snapshot picker for one network: checkbox list plus a Remove button below it. */
function SnapshotPicker({
  sourceId,
  network,
  canDelete,
  onBack,
  onRemove,
}: {
  sourceId: string;
  network: string;
  canDelete: boolean;
  onBack: () => void;
  onRemove: (snapshots: string[]) => void;
}) {
  const query = useBatfishSnapshotsQuery(sourceId, network);
  const [checked, setChecked] = useState<ReadonlySet<string>>(new Set());
  const snapshots = query.data?.snapshots ?? [];

  const toggle = (name: string, on: boolean) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (on) next.add(name);
      else next.delete(name);
      return next;
    });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">
          Snapshots of <span className="font-mono">{network}</span>
        </p>
        <Button type="button" variant="ghost" size="sm" onClick={onBack}>
          Back to networks
        </Button>
      </div>
      {query.isLoading ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : snapshots.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
          This network has no snapshots.
        </p>
      ) : (
        <ul className="max-h-72 divide-y overflow-y-auto rounded-lg border bg-card">
          {snapshots.map((snap) => {
            const id = `snapshot-${snap.name}`;
            return (
              <li key={snap.name} className="flex items-center gap-3 px-3 py-2">
                <Checkbox
                  id={id}
                  checked={checked.has(snap.name)}
                  onCheckedChange={(value) => toggle(snap.name, value === true)}
                />
                <label htmlFor={id} className="break-all text-xs">
                  {snapshotLabel(snap.name, snap.created_at)}
                </label>
              </li>
            );
          })}
        </ul>
      )}
      <Button
        type="button"
        variant="destructive"
        size="sm"
        className="h-8 gap-1.5 rounded-lg text-xs"
        disabled={!canDelete || checked.size === 0}
        onClick={() => onRemove([...checked])}
      >
        <Trash2 className="h-3.5 w-3.5" aria-hidden />
        Remove{checked.size ? ` (${checked.size})` : ""}
      </Button>
    </div>
  );
}

export function BatfishManageDialog({
  sourceId,
  onClose,
}: BatfishManageDialogProps) {
  const user = useAuthStore((state) => state.user);
  const canDelete = hasPermission(user, "sources.batfish", "write");
  const open = sourceId !== null;
  const summaries = useBatfishNetworkSummariesQuery(sourceId ?? "", open);
  const { deleteNetwork, deleteSnapshots } = useBatfishSourcesMutations();

  const [pickerNetwork, setPickerNetwork] = useState<string | null>(null);
  const [viewNetwork, setViewNetwork] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  // Set synchronously in confirm(): React state lags a click, so two quick clicks would
  // otherwise start two delete loops. The ref is the guard, the state drives the UI.
  const submittingRef = useRef(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [selectedNetworks, setSelectedNetworks] = useState<ReadonlySet<string>>(
    new Set(),
  );
  // Bumped after a snapshot delete so the picker remounts with an empty selection.
  const [pickerKey, setPickerKey] = useState(0);

  const close = () => {
    setPickerNetwork(null);
    setViewNetwork(null);
    setPending(null);
    setSelectedNetworks(new Set());
    onClose();
  };

  const finish = () => {
    submittingRef.current = false;
    setIsSubmitting(false);
    setPending(null);
  };

  const confirm = () => {
    if (!pending || !sourceId || submittingRef.current) return;
    submittingRef.current = true;
    setIsSubmitting(true);
    if (pending.kind === "networks") {
      const names = pending.networks;
      // One at a time: a failure toasts for that network and the rest still go through.
      void (async () => {
        for (const network of names) {
          try {
            await deleteNetwork.mutateAsync({ sourceId, network });
            // A removed network must not stay open in the other panels.
            setPickerNetwork((cur) => (cur === network ? null : cur));
            setViewNetwork((cur) => (cur === network ? null : cur));
          } catch {
            // the mutation's onError already showed a toast
          }
        }
        setSelectedNetworks(new Set());
        finish();
      })();
    } else {
      deleteSnapshots.mutate(
        { sourceId, network: pending.network, snapshots: pending.snapshots },
        {
          onSettled: () => {
            setPickerKey((key) => key + 1);
            finish();
          },
        },
      );
    }
  };
  const networks = summaries.data?.networks ?? [];
  // Drop selections of networks that no longer exist (e.g. just removed).
  const selected = networks
    .filter((net) => selectedNetworks.has(net.name))
    .map((net) => net.name);
  const allSelected =
    networks.length > 0 && selected.length === networks.length;
  const toggleNetwork = (name: string, on: boolean) =>
    setSelectedNetworks((prev) => {
      const next = new Set(prev);
      if (on) next.add(name);
      else next.delete(name);
      return next;
    });
  const isDeleting = isSubmitting;

  return (
    <>
      <Dialog open={open} onOpenChange={(next: boolean) => !next && close()}>
        <DialogContent className="flex max-h-[85vh] max-w-3xl flex-col gap-0 overflow-hidden p-0">
          <DialogHeader className="sr-only">
            <DialogTitle>Manage Batfish networks</DialogTitle>
            <DialogDescription>
              Networks and snapshots on the Batfish coordinator of {sourceId}.
            </DialogDescription>
          </DialogHeader>
          <div className="step-header px-4 py-2.5 text-sm font-semibold">
            Manage Batfish — <span className="font-mono">{sourceId}</span>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto bg-muted p-4">
            {pickerNetwork && sourceId ? (
              <SnapshotPicker
                key={pickerKey}
                sourceId={sourceId}
                network={pickerNetwork}
                canDelete={canDelete}
                onBack={() => setPickerNetwork(null)}
                onRemove={(snapshots) =>
                  setPending({
                    kind: "snapshots",
                    network: pickerNetwork,
                    snapshots,
                  })
                }
              />
            ) : summaries.isLoading ? (
              <p className="text-xs text-muted-foreground">Loading networks…</p>
            ) : summaries.isError ? (
              <p className="text-xs text-destructive">
                Could not load the networks: {summaries.error.message}
              </p>
            ) : (
              <div className="space-y-3">
                <div className="rounded-lg border bg-card">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-10">
                          <Checkbox
                            aria-label="Select all networks"
                            checked={allSelected}
                            disabled={!canDelete || networks.length === 0}
                            onCheckedChange={(value) =>
                              setSelectedNetworks(
                                value === true
                                  ? new Set(networks.map((n) => n.name))
                                  : new Set(),
                              )
                            }
                          />
                        </TableHead>
                        <TableHead>Network</TableHead>
                        <TableHead>Newest snapshot</TableHead>
                        <TableHead className="w-28">Snapshots</TableHead>
                        <TableHead>Action</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {summaries.data?.networks.length ? (
                        summaries.data.networks.map((net) => (
                          <TableRow key={net.name}>
                            <TableCell>
                              <Checkbox
                                aria-label={`Select ${net.name}`}
                                checked={selectedNetworks.has(net.name)}
                                disabled={!canDelete}
                                onCheckedChange={(value) =>
                                  toggleNetwork(net.name, value === true)
                                }
                              />
                            </TableCell>
                            <TableCell className="font-mono text-xs">
                              {net.name}
                            </TableCell>
                            <TableCell className="text-xs">
                              {net.latest_snapshot_at
                                ? formatSnapshotDate(net.latest_snapshot_at)
                                : "—"}
                            </TableCell>
                            <TableCell className="text-xs">
                              {net.unavailable ? "?" : net.snapshot_count}
                            </TableCell>
                            <TableCell>
                              <div className="flex gap-1">
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="icon"
                                  className="size-8 shrink-0"
                                  title="Remove Network"
                                  aria-label={`Remove network ${net.name}`}
                                  disabled={!canDelete || isDeleting}
                                  onClick={() =>
                                    setPending({
                                      kind: "networks",
                                      networks: [net.name],
                                    })
                                  }
                                >
                                  <Trash2
                                    className="size-3.5 text-destructive"
                                    aria-hidden
                                  />
                                </Button>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="icon"
                                  className="size-8 shrink-0"
                                  title="Remove Snapshots"
                                  aria-label={`Remove snapshots of ${net.name}`}
                                  disabled={!canDelete || isDeleting}
                                  onClick={() => setPickerNetwork(net.name)}
                                >
                                  <Layers
                                    className="size-3.5 text-destructive"
                                    aria-hidden
                                  />
                                </Button>
                                <Button
                                  type="button"
                                  variant="secondary"
                                  size="icon"
                                  className="size-8 shrink-0"
                                  title="Show Network"
                                  aria-label={`Show network ${net.name}`}
                                  onClick={() => setViewNetwork(net.name)}
                                >
                                  <Eye className="size-3.5" aria-hidden />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))
                      ) : (
                        <TableRow>
                          <TableCell
                            colSpan={5}
                            className="text-xs text-muted-foreground"
                          >
                            No networks on this coordinator.
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  className="h-8 gap-1.5 rounded-lg text-xs"
                  disabled={!canDelete || isDeleting || selected.length === 0}
                  onClick={() =>
                    setPending({ kind: "networks", networks: selected })
                  }
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  Remove{selected.length ? ` (${selected.length})` : ""}
                </Button>
              </div>
            )}
          </div>

          <DialogFooter className="shrink-0 border-t bg-card px-4 py-3">
            <Button type="button" variant="outline" size="sm" onClick={close}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {sourceId ? (
        <BatfishNetworkViewDialog
          sourceId={sourceId}
          network={viewNetwork}
          onClose={() => setViewNetwork(null)}
        />
      ) : null}

      <Dialog
        open={pending !== null}
        onOpenChange={(next: boolean) =>
          !next && !isDeleting && setPending(null)
        }
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {pending?.kind === "networks"
                ? pending.networks.length === 1
                  ? "Remove network?"
                  : "Remove networks?"
                : "Remove snapshots?"}
            </DialogTitle>
            <DialogDescription>
              {pending?.kind === "networks"
                ? `Delete ${
                    pending.networks.length === 1
                      ? `network "${pending.networks[0]}"`
                      : `${pending.networks.length} networks`
                  } with all snapshots? This cannot be undone, and workflows that use ${
                    pending.networks.length === 1
                      ? "this network"
                      : "these networks"
                  } will need a new snapshot.`
                : pending
                  ? `Delete ${pending.snapshots.length} snapshot(s) from "${pending.network}"? This cannot be undone.`
                  : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="border-t bg-card px-4 py-3">
            <Button
              type="button"
              variant="outline"
              disabled={isDeleting}
              onClick={() => setPending(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={isDeleting}
              onClick={confirm}
            >
              {isDeleting ? "Removing…" : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
