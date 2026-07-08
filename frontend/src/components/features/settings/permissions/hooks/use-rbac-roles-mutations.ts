"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

import type { Role, RoleCreatePayload, RoleUpdatePayload } from "../types";

export function useRbacRolesMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidateRoles = (roleId?: number) => {
    queryClient.invalidateQueries({ queryKey: queryKeys.rbac.roles() });
    if (roleId !== undefined) {
      queryClient.invalidateQueries({ queryKey: queryKeys.rbac.role(roleId) });
    }
  };

  const createRole = useMutation({
    mutationFn: (data: RoleCreatePayload) =>
      apiCall<Role>("rbac/roles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidateRoles();
      toast({ title: "Saved", description: "Role created." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const updateRole = useMutation({
    mutationFn: ({ id, data }: { id: number; data: RoleUpdatePayload }) =>
      apiCall<Role>(`rbac/roles/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (_result, { id }) => {
      invalidateRoles(id);
      toast({ title: "Saved", description: "Role updated." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const deleteRole = useMutation({
    mutationFn: (id: number) => apiCall<void>(`rbac/roles/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidateRoles();
      toast({ title: "Removed", description: "Role deleted." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const assignRolePermission = useMutation({
    mutationFn: ({ roleId, permissionId }: { roleId: number; permissionId: number }) =>
      apiCall<void>(`rbac/roles/${roleId}/permissions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role_id: roleId, permission_id: permissionId, granted: true }),
      }),
    onSuccess: (_result, { roleId }) => {
      invalidateRoles(roleId);
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const removeRolePermission = useMutation({
    mutationFn: ({ roleId, permissionId }: { roleId: number; permissionId: number }) =>
      apiCall<void>(`rbac/roles/${roleId}/permissions/${permissionId}`, { method: "DELETE" }),
    onSuccess: (_result, { roleId }) => {
      invalidateRoles(roleId);
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  return { createRole, updateRole, deleteRole, assignRolePermission, removeRolePermission };
}
