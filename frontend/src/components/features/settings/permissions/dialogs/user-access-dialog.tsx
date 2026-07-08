"use client";

import { useState } from "react";
import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useRbacPermissionsQuery } from "../hooks/use-rbac-permissions-query";
import { useRbacRolesQuery } from "../hooks/use-rbac-roles-query";
import { useRbacUserAccessMutations } from "../hooks/use-rbac-user-access-mutations";
import { useUserPermissionsQuery } from "../hooks/use-rbac-user-access-query";
import type { RbacUser } from "../types";

interface UserAccessDialogProps {
  open: boolean;
  user: RbacUser | null;
  onClose: () => void;
}

export function UserAccessDialog({ open, user, onClose }: UserAccessDialogProps) {
  const userId = open ? (user?.id ?? null) : null;
  const { data: access } = useUserPermissionsQuery(userId);
  const { data: roles } = useRbacRolesQuery();
  const { data: catalog } = useRbacPermissionsQuery();
  const { assignUserRole, removeUserRole, setUserPermissionOverride, removeUserPermissionOverride } =
    useRbacUserAccessMutations();

  const [selectedRoleId, setSelectedRoleId] = useState<string>("");
  const [selectedPermissionId, setSelectedPermissionId] = useState<string>("");
  const [overrideGrant, setOverrideGrant] = useState<"grant" | "deny">("grant");

  const assignedRoleNames = new Set(access?.roles ?? []);
  const availableRoles = (roles ?? []).filter((role) => !assignedRoleNames.has(role.name));

  const overriddenPermissionIds = new Set((access?.overrides ?? []).map((o) => o.id));
  const availablePermissions = (catalog ?? []).filter((p) => !overriddenPermissionIds.has(p.id));

  const handleAddRole = () => {
    if (!user || !selectedRoleId) {
      return;
    }
    assignUserRole.mutate({ userId: user.id, roleId: Number(selectedRoleId) });
    setSelectedRoleId("");
  };

  const handleRemoveRole = (roleName: string) => {
    if (!user) {
      return;
    }
    const role = (roles ?? []).find((r) => r.name === roleName);
    if (role) {
      removeUserRole.mutate({ userId: user.id, roleId: role.id });
    }
  };

  const handleAddOverride = () => {
    if (!user || !selectedPermissionId) {
      return;
    }
    setUserPermissionOverride.mutate({
      userId: user.id,
      permissionId: Number(selectedPermissionId),
      granted: overrideGrant === "grant",
    });
    setSelectedPermissionId("");
  };

  const handleRemoveOverride = (permissionId: number) => {
    if (!user) {
      return;
    }
    removeUserPermissionOverride.mutate({ userId: user.id, permissionId });
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Access for {user?.username ?? "user"}</DialogTitle>
          <DialogDescription>
            Assign roles and, if needed, grant or deny individual permissions that
            override the roles above.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-6 overflow-y-auto pr-1">
          <section>
            <p className="mb-2 text-sm font-semibold">Roles</p>
            <div className="mb-3 flex flex-wrap gap-2">
              {(access?.roles ?? []).length === 0 ? (
                <span className="text-sm text-muted-foreground">No roles assigned</span>
              ) : (
                access?.roles.map((roleName) => (
                  <Badge key={roleName} className="gap-1" variant="outline">
                    {roleName}
                    <button
                      aria-label={`Remove ${roleName} role`}
                      type="button"
                      onClick={() => handleRemoveRole(roleName)}
                    >
                      <X className="size-3" />
                    </button>
                  </Badge>
                ))
              )}
            </div>
            <div className="flex gap-2">
              <Select value={selectedRoleId} onValueChange={setSelectedRoleId}>
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder="Select a role to assign" />
                </SelectTrigger>
                <SelectContent>
                  {availableRoles.map((role) => (
                    <SelectItem key={role.id} value={String(role.id)}>
                      {role.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button disabled={!selectedRoleId} type="button" onClick={handleAddRole}>
                Assign
              </Button>
            </div>
          </section>

          <section>
            <p className="mb-2 text-sm font-semibold">Permission overrides</p>
            <div className="mb-3 space-y-2">
              {(access?.overrides ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No overrides configured</p>
              ) : (
                access?.overrides.map((override) => (
                  <div
                    key={override.id}
                    className="flex items-center justify-between rounded-lg border px-3 py-2"
                  >
                    <div className="flex items-center gap-2 text-sm">
                      <span className="font-mono">
                        {override.resource}:{override.action}
                      </span>
                      <Badge variant={override.granted ? "secondary" : "destructive"}>
                        {override.granted ? "Grant" : "Deny"}
                      </Badge>
                    </div>
                    <Button
                      aria-label="Remove override"
                      size="icon"
                      type="button"
                      variant="ghost"
                      onClick={() => handleRemoveOverride(override.id)}
                    >
                      <X className="size-4" />
                    </Button>
                  </div>
                ))
              )}
            </div>
            <div className="flex gap-2">
              <Select value={selectedPermissionId} onValueChange={setSelectedPermissionId}>
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder="Select a permission" />
                </SelectTrigger>
                <SelectContent>
                  {availablePermissions.map((permission) => (
                    <SelectItem key={permission.id} value={String(permission.id)}>
                      {permission.resource}:{permission.action}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={overrideGrant}
                onValueChange={(value) => setOverrideGrant(value as "grant" | "deny")}
              >
                <SelectTrigger className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="grant">Grant</SelectItem>
                  <SelectItem value="deny">Deny</SelectItem>
                </SelectContent>
              </Select>
              <Button disabled={!selectedPermissionId} type="button" onClick={handleAddOverride}>
                Add
              </Button>
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
