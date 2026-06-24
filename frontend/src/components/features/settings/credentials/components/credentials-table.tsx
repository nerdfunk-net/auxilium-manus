"use client";

import { Pencil, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";

import { CredentialStatusBadge } from "../components/credential-status-badge";
import type { Credential } from "../types";
import { formatValidUntil } from "../utils/credential-utils";

interface CredentialsTableProps {
  credentials: Credential[];
  onEdit: (credential: Credential) => void;
  onDelete: (credential: Credential) => void;
}

export function CredentialsTable({
  credentials,
  onEdit,
  onDelete,
}: CredentialsTableProps) {
  if (credentials.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
        No SSH login credentials configured yet.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {credentials.map((credential) => (
        <li
          key={credential.id}
          className="grid gap-3 rounded-lg border bg-background px-4 py-3 md:grid-cols-[4rem_1fr_1fr_8rem_7rem_auto]"
        >
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              ID
            </p>
            <p className="font-mono text-sm">{credential.id}</p>
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Credential ID
            </p>
            <p className="truncate font-mono text-sm">{credential.name}</p>
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Username
            </p>
            <p className="truncate text-sm">{credential.username}</p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Valid until
            </p>
            <p className="text-sm">{formatValidUntil(credential.valid_until)}</p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Status
            </p>
            <CredentialStatusBadge status={credential.status} />
          </div>
          <div className="flex items-end justify-end gap-1">
            <Button
              aria-label={`Edit ${credential.name}`}
              size="icon"
              type="button"
              variant="ghost"
              onClick={() => onEdit(credential)}
            >
              <Pencil className="size-4" />
            </Button>
            <Button
              aria-label={`Delete ${credential.name}`}
              size="icon"
              type="button"
              variant="ghost"
              onClick={() => onDelete(credential)}
            >
              <Trash2 className="size-4 text-destructive" />
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}
