"use client";

import { useMemo } from "react";
import { Pencil, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";

import { CredentialBackendBadge } from "../components/credential-backend-badge";
import { CredentialStatusBadge } from "../components/credential-status-badge";
import { CredentialTypeBadge } from "../components/credential-type-badge";
import { CredentialVisibilityBadge } from "../components/credential-visibility-badge";
import { useResizableColumns, type ResizableColumn } from "../hooks/use-resizable-columns";
import type { Credential } from "../types";
import { formatValidUntil } from "../utils/credential-utils";
import { sharedSecretAlgorithmLabel } from "@/lib/shared-secret-algorithms";
import { ColumnResizeHandle } from "./column-resize-handle";

interface CredentialsTableProps {
  credentials: Credential[];
  onEdit: (credential: Credential) => void;
  onDelete: (credential: Credential) => void;
}

// Module-level so the array identity is stable for the hook's effect.
const COLUMNS: readonly (ResizableColumn & { label: string })[] = [
  { key: "id", label: "ID", defaultWidth: 36, minWidth: 32 },
  { key: "name", label: "Credential ID", defaultWidth: 150, minWidth: 80 },
  { key: "username", label: "Username", defaultWidth: 130, minWidth: 60 },
  { key: "type", label: "Type", defaultWidth: 112, minWidth: 60 },
  { key: "valid_until", label: "Valid until", defaultWidth: 68, minWidth: 56 },
  { key: "status", label: "Status", defaultWidth: 56, minWidth: 48 },
  { key: "visibility", label: "Visibility", defaultWidth: 64, minWidth: 56 },
  { key: "backend", label: "Backend", defaultWidth: 56, minWidth: 48 },
];

const ACTIONS_WIDTH = "5rem";
const HEADER_CLASS =
  "text-[10px] font-semibold uppercase tracking-wide text-muted-foreground";

export function CredentialsTable({
  credentials,
  onEdit,
  onDelete,
}: CredentialsTableProps) {
  const { widths, resizeBy, commit, reset } = useResizableColumns(
    "credentials-table-v2",
    COLUMNS,
  );

  const gridTemplateColumns = useMemo(
    () => [...COLUMNS.map((c) => `${widths[c.key]}px`), ACTIONS_WIDTH].join(" "),
    [widths],
  );

  if (credentials.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
        No credentials configured yet.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <div
        aria-label="Credentials"
        className="min-w-max space-y-2"
        role="table"
      >
        <div
          className="grid gap-3 px-4 pt-1"
          role="row"
          style={{ gridTemplateColumns }}
        >
          {COLUMNS.map((column) => (
            <div
              key={column.key}
              className="relative min-w-0"
              role="columnheader"
            >
              <p className={HEADER_CLASS}>{column.label}</p>
              <ColumnResizeHandle
                label={column.label}
                width={widths[column.key]}
                onCommit={commit}
                onReset={reset}
                onResize={(delta, startWidth) =>
                  resizeBy(column.key, delta, startWidth)
                }
              />
            </div>
          ))}
          <div role="columnheader">
            <span className="sr-only">Actions</span>
          </div>
        </div>

        <ul className="space-y-2" role="rowgroup">
          {credentials.map((credential) => (
            <li
              key={credential.id}
              className="grid items-center gap-3 rounded-lg border bg-background px-4 py-3"
              role="row"
              style={{ gridTemplateColumns }}
            >
              <p className="truncate font-mono text-sm" role="cell">
                {credential.id}
              </p>
              <p
                className="truncate font-mono text-sm"
                role="cell"
                title={credential.name}
              >
                {credential.name}
              </p>
              <p
                className="truncate text-sm"
                role="cell"
                title={credential.username}
              >
                {credential.username}
              </p>
              <div className="min-w-0" role="cell">
                <CredentialTypeBadge type={credential.type} />
                {credential.type === "shared_secret" ? (
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {sharedSecretAlgorithmLabel(credential.algorithm)}
                  </p>
                ) : null}
              </div>
              <p className="truncate text-sm" role="cell">
                {formatValidUntil(credential.valid_until)}
              </p>
              <div className="min-w-0" role="cell">
                <CredentialStatusBadge status={credential.status} />
              </div>
              <div className="min-w-0" role="cell">
                <CredentialVisibilityBadge visibility={credential.visibility} />
                {credential.visibility === "private" && credential.owner_username ? (
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {credential.owner_username}
                  </p>
                ) : null}
              </div>
              <div className="min-w-0" role="cell">
                <CredentialBackendBadge backend={credential.storage_backend} />
              </div>
              <div className="flex items-center justify-end gap-1" role="cell">
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
      </div>
    </div>
  );
}
