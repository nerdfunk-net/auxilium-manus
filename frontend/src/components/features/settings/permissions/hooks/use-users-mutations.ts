"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

import type { RbacUser, UserCreatePayload, UserUpdatePayload } from "../types";

export function useUsersMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = (userId?: number) => {
    queryClient.invalidateQueries({ queryKey: queryKeys.users.list() });
    if (userId !== undefined) {
      queryClient.invalidateQueries({ queryKey: queryKeys.users.detail(userId) });
    }
  };

  const createUser = useMutation({
    mutationFn: (data: UserCreatePayload) =>
      apiCall<RbacUser>("users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "User created." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const updateUser = useMutation({
    mutationFn: ({ id, data }: { id: number; data: UserUpdatePayload }) =>
      apiCall<RbacUser>(`users/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (_result, { id }) => {
      invalidate(id);
      toast({ title: "Saved", description: "User updated." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const deleteUser = useMutation({
    mutationFn: (id: number) => apiCall<void>(`users/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Removed", description: "User deleted." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const setUserActive = useMutation({
    mutationFn: ({ id, isActive }: { id: number; isActive: boolean }) =>
      apiCall<RbacUser>(`users/${id}/activate?is_active=${isActive}`, {
        method: "PATCH",
      }),
    onSuccess: (_result, { id }) => {
      invalidate(id);
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  return { createUser, updateUser, deleteUser, setUserActive };
}
