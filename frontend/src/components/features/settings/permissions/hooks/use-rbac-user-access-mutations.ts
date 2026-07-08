"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useRbacUserAccessMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidateUser = (userId: number) => {
    queryClient.invalidateQueries({ queryKey: queryKeys.rbac.userPermissions(userId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.users.list() });
    queryClient.invalidateQueries({ queryKey: queryKeys.users.detail(userId) });
  };

  const assignUserRole = useMutation({
    mutationFn: ({ userId, roleId }: { userId: number; roleId: number }) =>
      apiCall<void>(`rbac/users/${userId}/roles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, role_id: roleId }),
      }),
    onSuccess: (_result, { userId }) => {
      invalidateUser(userId);
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const removeUserRole = useMutation({
    mutationFn: ({ userId, roleId }: { userId: number; roleId: number }) =>
      apiCall<void>(`rbac/users/${userId}/roles/${roleId}`, { method: "DELETE" }),
    onSuccess: (_result, { userId }) => {
      invalidateUser(userId);
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const setUserPermissionOverride = useMutation({
    mutationFn: ({
      userId,
      permissionId,
      granted,
    }: {
      userId: number;
      permissionId: number;
      granted: boolean;
    }) =>
      apiCall<void>(`rbac/users/${userId}/permissions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, permission_id: permissionId, granted }),
      }),
    onSuccess: (_result, { userId }) => {
      invalidateUser(userId);
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const removeUserPermissionOverride = useMutation({
    mutationFn: ({ userId, permissionId }: { userId: number; permissionId: number }) =>
      apiCall<void>(`rbac/users/${userId}/permissions/${permissionId}`, { method: "DELETE" }),
    onSuccess: (_result, { userId }) => {
      invalidateUser(userId);
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  return {
    assignUserRole,
    removeUserRole,
    setUserPermissionOverride,
    removeUserPermissionOverride,
  };
}
