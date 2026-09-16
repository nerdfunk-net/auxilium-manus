"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

import type {
  SecretManagerBackend,
  SecretManagerConnectionRecord,
} from "./use-secret-manager-connections-query";

export interface SecretManagerConnectionUpsertPayload {
  name: string;
  backend: SecretManagerBackend;
  credential_name?: string | null;
  verify_ssl: boolean;
  is_active?: boolean;
  description?: string | null;
  backend_config: Record<string, unknown>;
}

export interface SecretManagerConnectionTestResult {
  success: boolean;
  message: string;
}

export function useSecretManagerConnectionsMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.secretManagerConnections.all });

  const createConnection = useMutation({
    mutationFn: (data: SecretManagerConnectionUpsertPayload) =>
      apiCall<SecretManagerConnectionRecord>("secret-manager/connections", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Secret manager connection configured." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const updateConnection = useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: number;
      data: Partial<SecretManagerConnectionUpsertPayload>;
    }) =>
      apiCall<SecretManagerConnectionRecord>(`secret-manager/connections/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Secret manager connection updated." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const deleteConnection = useMutation({
    mutationFn: (id: number) =>
      apiCall<void>(`secret-manager/connections/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Removed", description: "Secret manager connection deleted." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const testConnection = useMutation({
    mutationFn: (id: number) =>
      apiCall<SecretManagerConnectionTestResult>(`secret-manager/connections/${id}/test`, {
        method: "POST",
      }),
    onSuccess: (data) => {
      toast({
        title: data.success ? "Connection successful" : "Connection failed",
        description: data.message,
        variant: data.success ? "default" : "destructive",
      });
    },
    onError: (error: Error) => {
      toast({ title: "Connection failed", description: error.message, variant: "destructive" });
    },
  });

  return useMemo(
    () => ({ createConnection, updateConnection, deleteConnection, testConnection }),
    [createConnection, updateConnection, deleteConnection, testConnection],
  );
}
