"use client";

import { useCallback, useMemo, useState } from "react";
import { Plus, Shield } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { PermissionsCatalog } from "../permissions/components/permissions-catalog";
import { RolesTable } from "../permissions/components/roles-table";
import { UsersTable } from "../permissions/components/users-table";
import { DeleteRoleDialog } from "../permissions/dialogs/delete-role-dialog";
import { DeleteUserDialog } from "../permissions/dialogs/delete-user-dialog";
import { RoleDialog } from "../permissions/dialogs/role-dialog";
import { RolePermissionsDialog } from "../permissions/dialogs/role-permissions-dialog";
import { UserAccessDialog } from "../permissions/dialogs/user-access-dialog";
import { UserDialog } from "../permissions/dialogs/user-dialog";
import { useRbacPermissionsQuery } from "../permissions/hooks/use-rbac-permissions-query";
import { useRbacRolesMutations } from "../permissions/hooks/use-rbac-roles-mutations";
import { useRbacRolesQuery } from "../permissions/hooks/use-rbac-roles-query";
import { useUsersMutations } from "../permissions/hooks/use-users-mutations";
import { useUsersQuery } from "../permissions/hooks/use-users-query";
import type { RbacUser, Role } from "../permissions/types";

type RoleDialogState =
  | { type: "closed" }
  | { type: "create" }
  | { type: "edit"; role: Role }
  | { type: "delete"; role: Role }
  | { type: "permissions"; role: Role };

type UserDialogState =
  | { type: "closed" }
  | { type: "create" }
  | { type: "edit"; user: RbacUser }
  | { type: "delete"; user: RbacUser }
  | { type: "access"; user: RbacUser };

export function PermissionsSettingsCanvas() {
  const currentUser = useAuthStore((state) => state.user);
  const canManageRoles = hasPermission(currentUser, "rbac.roles", "write");
  const canManageUsers = hasPermission(currentUser, "users", "write");

  const [roleDialog, setRoleDialog] = useState<RoleDialogState>({ type: "closed" });
  const [userDialog, setUserDialog] = useState<UserDialogState>({ type: "closed" });

  const { data: rolesData, isLoading: rolesLoading } = useRbacRolesQuery();
  const { data: usersData, isLoading: usersLoading } = useUsersQuery();
  const { data: permissionsData, isLoading: permissionsLoading } = useRbacPermissionsQuery();

  const { createRole, updateRole, deleteRole } = useRbacRolesMutations();
  const { createUser, updateUser, deleteUser } = useUsersMutations();

  const roles = useMemo(() => rolesData ?? [], [rolesData]);
  const users = useMemo(() => usersData?.users ?? [], [usersData]);
  const permissions = useMemo(() => permissionsData ?? [], [permissionsData]);

  const handleCreateRole = useCallback(
    (values: { name: string; description?: string }) => {
      createRole.mutate(
        { name: values.name.trim(), description: values.description?.trim() || undefined },
        { onSuccess: () => setRoleDialog({ type: "closed" }) },
      );
    },
    [createRole],
  );

  const handleUpdateRole = useCallback(
    (role: Role, values: { name: string; description?: string }) => {
      updateRole.mutate(
        {
          id: role.id,
          data: { name: values.name.trim(), description: values.description?.trim() || undefined },
        },
        { onSuccess: () => setRoleDialog({ type: "closed" }) },
      );
    },
    [updateRole],
  );

  const confirmDeleteRole = useCallback(() => {
    if (roleDialog.type !== "delete") {
      return;
    }
    deleteRole.mutate(roleDialog.role.id, { onSuccess: () => setRoleDialog({ type: "closed" }) });
  }, [deleteRole, roleDialog]);

  const handleCreateUser = useCallback(
    (values: { username: string; password?: string; is_active: boolean }) => {
      createUser.mutate(
        {
          username: values.username.trim(),
          password: values.password ?? "",
          is_active: values.is_active,
        },
        { onSuccess: () => setUserDialog({ type: "closed" }) },
      );
    },
    [createUser],
  );

  const handleUpdateUser = useCallback(
    (user: RbacUser, values: { username: string; password?: string; is_active: boolean }) => {
      const payload: { username?: string; password?: string; is_active?: boolean } = {
        username: values.username.trim(),
        is_active: values.is_active,
      };
      if (values.password?.trim()) {
        payload.password = values.password;
      }
      updateUser.mutate(
        { id: user.id, data: payload },
        { onSuccess: () => setUserDialog({ type: "closed" }) },
      );
    },
    [updateUser],
  );

  const confirmDeleteUser = useCallback(() => {
    if (userDialog.type !== "delete") {
      return;
    }
    deleteUser.mutate(userDialog.user.id, { onSuccess: () => setUserDialog({ type: "closed" }) });
  }, [deleteUser, userDialog]);

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-slate-50 p-8">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Shield className="size-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">Users &amp; Permissions</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Manage local accounts, roles, and role-based access control.
            </p>
          </div>
        </div>

        <Tabs defaultValue="roles">
          <TabsList>
            <TabsTrigger value="roles">Roles</TabsTrigger>
            <TabsTrigger value="users">Users</TabsTrigger>
            <TabsTrigger value="permissions">Permissions</TabsTrigger>
          </TabsList>

          <TabsContent value="roles" className="space-y-4">
            <div className="flex justify-end">
              {canManageRoles ? (
                <Button type="button" onClick={() => setRoleDialog({ type: "create" })}>
                  <Plus className="size-4" />
                  Create role
                </Button>
              ) : null}
            </div>
            {rolesLoading ? (
              <p className="text-sm text-muted-foreground">Loading roles…</p>
            ) : (
              <RolesTable
                roles={roles}
                onDelete={(role) => setRoleDialog({ type: "delete", role })}
                onEdit={(role) => setRoleDialog({ type: "edit", role })}
                onManagePermissions={(role) => setRoleDialog({ type: "permissions", role })}
              />
            )}
          </TabsContent>

          <TabsContent value="users" className="space-y-4">
            <div className="flex justify-end">
              {canManageUsers ? (
                <Button type="button" onClick={() => setUserDialog({ type: "create" })}>
                  <Plus className="size-4" />
                  Create user
                </Button>
              ) : null}
            </div>
            {usersLoading ? (
              <p className="text-sm text-muted-foreground">Loading users…</p>
            ) : (
              <UsersTable
                users={users}
                onDelete={(user) => setUserDialog({ type: "delete", user })}
                onEdit={(user) => setUserDialog({ type: "edit", user })}
                onManageAccess={(user) => setUserDialog({ type: "access", user })}
              />
            )}
          </TabsContent>

          <TabsContent value="permissions" className="space-y-4">
            {permissionsLoading ? (
              <p className="text-sm text-muted-foreground">Loading permissions…</p>
            ) : (
              <PermissionsCatalog permissions={permissions} />
            )}
          </TabsContent>
        </Tabs>
      </div>

      <RoleDialog
        mode="create"
        open={roleDialog.type === "create"}
        isSaving={createRole.isPending}
        onClose={() => setRoleDialog({ type: "closed" })}
        onSubmit={handleCreateRole}
      />
      <RoleDialog
        mode="edit"
        open={roleDialog.type === "edit"}
        role={roleDialog.type === "edit" ? roleDialog.role : undefined}
        isSaving={updateRole.isPending}
        onClose={() => setRoleDialog({ type: "closed" })}
        onSubmit={(values) => {
          if (roleDialog.type === "edit") {
            handleUpdateRole(roleDialog.role, values);
          }
        }}
      />
      <DeleteRoleDialog
        open={roleDialog.type === "delete"}
        roleName={roleDialog.type === "delete" ? roleDialog.role.name : undefined}
        isDeleting={deleteRole.isPending}
        onClose={() => setRoleDialog({ type: "closed" })}
        onConfirm={confirmDeleteRole}
      />
      <RolePermissionsDialog
        open={roleDialog.type === "permissions"}
        role={roleDialog.type === "permissions" ? roleDialog.role : null}
        onClose={() => setRoleDialog({ type: "closed" })}
      />

      <UserDialog
        mode="create"
        open={userDialog.type === "create"}
        isSaving={createUser.isPending}
        onClose={() => setUserDialog({ type: "closed" })}
        onSubmit={handleCreateUser}
      />
      <UserDialog
        mode="edit"
        open={userDialog.type === "edit"}
        user={userDialog.type === "edit" ? userDialog.user : undefined}
        isSaving={updateUser.isPending}
        onClose={() => setUserDialog({ type: "closed" })}
        onSubmit={(values) => {
          if (userDialog.type === "edit") {
            handleUpdateUser(userDialog.user, values);
          }
        }}
      />
      <DeleteUserDialog
        open={userDialog.type === "delete"}
        username={userDialog.type === "delete" ? userDialog.user.username : undefined}
        isDeleting={deleteUser.isPending}
        onClose={() => setUserDialog({ type: "closed" })}
        onConfirm={confirmDeleteUser}
      />
      <UserAccessDialog
        open={userDialog.type === "access"}
        user={userDialog.type === "access" ? userDialog.user : null}
        onClose={() => setUserDialog({ type: "closed" })}
      />
    </div>
  );
}
