"use client";

import { useState } from "react";
import { Plus, ShieldCheck } from "lucide-react";

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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useSecretManagerConnectionsMutations } from "@/hooks/queries/use-secret-manager-connections-mutations";
import {
  useSecretManagerConnectionsQuery,
  type SecretManagerConnectionRecord,
} from "@/hooks/queries/use-secret-manager-connections-query";

import { SecretManagerConnectionDialog } from "../dialogs/secret-manager-connection-dialog";

const BACKEND_LABELS: Record<string, string> = {
  openbao: "OpenBao",
  infisical: "Infisical",
};

export function SecretManagerSettingsCanvas() {
  const { data, isLoading, error } = useSecretManagerConnectionsQuery({ activeOnly: false });
  const { deleteConnection, testConnection } = useSecretManagerConnectionsMutations();

  const [editing, setEditing] = useState<SecretManagerConnectionRecord | null | undefined>(
    undefined,
  );
  const [deleteTarget, setDeleteTarget] = useState<SecretManagerConnectionRecord | null>(null);

  const connections = data?.connections ?? [];

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-muted p-8">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <ShieldCheck className="size-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Secret Manager</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Connections to an external secret manager (OpenBao or Infisical) used by the
                secret-get / secret-set / secret-generate workflow steps to read, write, and
                rotate operational network secrets — TACACS+ keys, SNMP credentials, and similar.
                Browsing stored secrets happens in the backend&apos;s own UI, not here; this page
                only manages connections.
              </p>
            </div>
          </div>
          <Button type="button" onClick={() => setEditing(null)}>
            <Plus className="size-4" />
            Add connection
          </Button>
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : error ? (
          <p className="text-sm text-destructive">
            Failed to load Secret Manager connections: {error.message}
          </p>
        ) : connections.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No connections configured yet. Add one to enable the secret-get / secret-set /
            secret-generate workflow steps.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Backend</TableHead>
                <TableHead>Credential</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {connections.map((connection) => (
                <TableRow key={connection.id}>
                  <TableCell className="font-medium">{connection.name}</TableCell>
                  <TableCell>{BACKEND_LABELS[connection.backend] ?? connection.backend}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {connection.credential_name ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={connection.is_active ? "default" : "outline"}>
                      {connection.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell className="flex justify-end gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={testConnection.isPending}
                      onClick={() => testConnection.mutate(connection.id)}
                    >
                      Test
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => setEditing(connection)}
                    >
                      Edit
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => setDeleteTarget(connection)}
                    >
                      Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <SecretManagerConnectionDialog
        open={editing !== undefined}
        connection={editing ?? null}
        onClose={() => setEditing(undefined)}
      />

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Remove Secret Manager connection?</DialogTitle>
            <DialogDescription>
              {deleteTarget
                ? `Workflow steps referencing "${deleteTarget.name}" will fail until reconfigured. Secrets already stored in ${BACKEND_LABELS[deleteTarget.backend] ?? deleteTarget.backend} are not deleted.`
                : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleteConnection.isPending}
              onClick={() => {
                if (!deleteTarget) return;
                deleteConnection.mutate(deleteTarget.id, {
                  onSuccess: () => setDeleteTarget(null),
                });
              }}
            >
              {deleteConnection.isPending ? "Removing…" : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
