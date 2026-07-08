"use client";

import { Pencil, ShieldCheck, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import type { Role } from "../types";

interface RolesTableProps {
  roles: Role[];
  onEdit: (role: Role) => void;
  onDelete: (role: Role) => void;
  onManagePermissions: (role: Role) => void;
}

export function RolesTable({ roles, onEdit, onDelete, onManagePermissions }: RolesTableProps) {
  if (roles.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
        No roles defined yet.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {roles.map((role) => (
        <li
          key={role.id}
          className="grid gap-3 rounded-lg border bg-background px-4 py-3 md:grid-cols-[1fr_2fr_6rem_auto]"
        >
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Name
            </p>
            <p className="truncate text-sm font-medium">{role.name}</p>
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Description
            </p>
            <p className="truncate text-sm text-muted-foreground">
              {role.description ?? "—"}
            </p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Type
            </p>
            {role.is_system ? (
              <Badge variant="secondary">System</Badge>
            ) : (
              <Badge variant="outline">Custom</Badge>
            )}
          </div>
          <div className="flex items-end justify-end gap-1">
            <Button
              aria-label={`Manage permissions for ${role.name}`}
              size="icon"
              type="button"
              variant="ghost"
              onClick={() => onManagePermissions(role)}
            >
              <ShieldCheck className="size-4" />
            </Button>
            <Button
              aria-label={`Edit ${role.name}`}
              size="icon"
              type="button"
              variant="ghost"
              onClick={() => onEdit(role)}
            >
              <Pencil className="size-4" />
            </Button>
            <Button
              aria-label={`Delete ${role.name}`}
              disabled={role.is_system}
              size="icon"
              type="button"
              variant="ghost"
              onClick={() => onDelete(role)}
            >
              <Trash2 className="size-4 text-destructive" />
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}
