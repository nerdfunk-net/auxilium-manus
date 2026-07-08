"use client";

import { Pencil, Trash2, Users as UsersIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import type { RbacUser } from "../types";

interface UsersTableProps {
  users: RbacUser[];
  onEdit: (user: RbacUser) => void;
  onDelete: (user: RbacUser) => void;
  onManageAccess: (user: RbacUser) => void;
}

export function UsersTable({ users, onEdit, onDelete, onManageAccess }: UsersTableProps) {
  if (users.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
        No users found.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {users.map((user) => (
        <li
          key={user.id}
          className="grid gap-3 rounded-lg border bg-background px-4 py-3 md:grid-cols-[1fr_2fr_6rem_auto]"
        >
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Username
            </p>
            <p className="truncate text-sm font-medium">{user.username}</p>
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Roles
            </p>
            <div className="flex flex-wrap gap-1">
              {user.roles.length === 0 ? (
                <span className="text-sm text-muted-foreground">No roles assigned</span>
              ) : (
                user.roles.map((role) => (
                  <Badge key={role} variant="outline">
                    {role}
                  </Badge>
                ))
              )}
            </div>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Status
            </p>
            <Badge variant={user.is_active ? "secondary" : "destructive"}>
              {user.is_active ? "Active" : "Inactive"}
            </Badge>
          </div>
          <div className="flex items-end justify-end gap-1">
            <Button
              aria-label={`Manage access for ${user.username}`}
              size="icon"
              type="button"
              variant="ghost"
              onClick={() => onManageAccess(user)}
            >
              <UsersIcon className="size-4" />
            </Button>
            <Button
              aria-label={`Edit ${user.username}`}
              size="icon"
              type="button"
              variant="ghost"
              onClick={() => onEdit(user)}
            >
              <Pencil className="size-4" />
            </Button>
            <Button
              aria-label={`Delete ${user.username}`}
              size="icon"
              type="button"
              variant="ghost"
              onClick={() => onDelete(user)}
            >
              <Trash2 className="size-4 text-destructive" />
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}
