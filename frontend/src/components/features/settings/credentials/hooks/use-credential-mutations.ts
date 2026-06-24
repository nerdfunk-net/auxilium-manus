"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

import type {
  Credential,
  CredentialCreatePayload,
  CredentialUpdatePayload,
} from "../types";

export function useCredentialMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.credentials.all });
  };

  const createCredential = useMutation({
    mutationFn: (data: CredentialCreatePayload) =>
      apiCall<Credential>("credentials", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "SSH login credential created." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const updateCredential = useMutation({
    mutationFn: ({ id, data }: { id: number; data: CredentialUpdatePayload }) =>
      apiCall<Credential>(`credentials/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "SSH login credential updated." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const deleteCredential = useMutation({
    mutationFn: (id: number) =>
      apiCall<void>(`credentials/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Removed", description: "SSH login credential deleted." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  return { createCredential, updateCredential, deleteCredential };
}
