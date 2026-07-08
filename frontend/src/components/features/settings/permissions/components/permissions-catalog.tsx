"use client";

import { Badge } from "@/components/ui/badge";

import type { Permission } from "../types";
import { getActionVariant, groupPermissionsByResource } from "../utils/rbac-utils";

interface PermissionsCatalogProps {
  permissions: Permission[];
}

export function PermissionsCatalog({ permissions }: PermissionsCatalogProps) {
  if (permissions.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
        No permissions defined yet.
      </p>
    );
  }

  const groups = groupPermissionsByResource(permissions);

  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <div key={group.resource} className="rounded-lg border bg-background p-4">
          <p className="mb-3 font-mono text-sm font-semibold">{group.resource}</p>
          <ul className="space-y-2">
            {group.permissions.map((permission) => (
              <li
                key={permission.id}
                className="flex items-center justify-between gap-3 text-sm"
              >
                <div className="flex items-center gap-2">
                  <Badge variant={getActionVariant(permission.action)}>
                    {permission.action}
                  </Badge>
                  <span className="text-muted-foreground">
                    {permission.description ?? "—"}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
