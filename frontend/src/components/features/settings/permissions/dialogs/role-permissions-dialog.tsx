"use client";

import { useMemo } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";

import { useRbacPermissionsQuery } from "../hooks/use-rbac-permissions-query";
import { useRbacRoleQuery } from "../hooks/use-rbac-roles-query";
import { useRbacRolesMutations } from "../hooks/use-rbac-roles-mutations";
import type { Role } from "../types";
import { groupPermissionsByResource } from "../utils/rbac-utils";

interface RolePermissionsDialogProps {
  open: boolean;
  role: Role | null;
  onClose: () => void;
}

export function RolePermissionsDialog({ open, role, onClose }: RolePermissionsDialogProps) {
  const { data: catalog } = useRbacPermissionsQuery();
  const { data: roleDetail } = useRbacRoleQuery(open ? (role?.id ?? null) : null);
  const { assignRolePermission, removeRolePermission } = useRbacRolesMutations();

  const grantedIds = useMemo(
    () => new Set((roleDetail?.permissions ?? []).map((permission) => permission.id)),
    [roleDetail],
  );

  const groups = useMemo(() => groupPermissionsByResource(catalog ?? []), [catalog]);

  const handleToggle = (permissionId: number, currentlyGranted: boolean) => {
    if (!role) {
      return;
    }
    if (currentlyGranted) {
      removeRolePermission.mutate({ roleId: role.id, permissionId });
    } else {
      assignRolePermission.mutate({ roleId: role.id, permissionId });
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Permissions for {role?.name ?? "role"}</DialogTitle>
          <DialogDescription>
            Toggle which permissions this role grants. Changes apply immediately.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          {groups.map((group) => (
            <div key={group.resource} className="rounded-lg border p-4">
              <p className="mb-3 font-mono text-sm font-semibold">{group.resource}</p>
              <ul className="space-y-2">
                {group.permissions.map((permission) => {
                  const granted = grantedIds.has(permission.id);
                  return (
                    <li key={permission.id} className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium">{permission.action}</p>
                        <p className="truncate text-xs text-muted-foreground">
                          {permission.description ?? "—"}
                        </p>
                      </div>
                      <Switch
                        checked={granted}
                        disabled={role?.is_system && role.name === "admin"}
                        onCheckedChange={() => handleToggle(permission.id, granted)}
                      />
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
