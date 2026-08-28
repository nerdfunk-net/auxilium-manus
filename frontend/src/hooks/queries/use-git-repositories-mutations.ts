"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

import type { GitRepositoryAuthType, GitRepositoryRecord } from "./use-git-repositories-query";

export interface GitRepositoryUpsertPayload {
  name: string;
  category: string;
  url: string;
  branch: string;
  auth_type: GitRepositoryAuthType;
  credential_name?: string | null;
  path?: string | null;
  verify_ssl: boolean;
  git_author_name?: string | null;
  git_author_email?: string | null;
  description?: string | null;
  is_active?: boolean;
}

export interface GitConnectionTestPayload {
  url: string;
  branch: string;
  auth_type: GitRepositoryAuthType;
  credential_name?: string | null;
  verify_ssl: boolean;
}

export interface GitConnectionTestResult {
  success: boolean;
  message: string;
  details?: Record<string, unknown> | null;
}

export function useGitRepositoriesMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.gitRepositories.all });

  const createRepository = useMutation({
    mutationFn: (data: GitRepositoryUpsertPayload) =>
      apiCall<GitRepositoryRecord>("git-repositories", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Git repository configured." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const updateRepository = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<GitRepositoryUpsertPayload> }) =>
      apiCall<GitRepositoryRecord>(`git-repositories/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Git repository updated." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const deleteRepository = useMutation({
    mutationFn: (id: number) => apiCall<void>(`git-repositories/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Removed", description: "Git repository deleted." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const testConnection = useMutation({
    mutationFn: (data: GitConnectionTestPayload) =>
      apiCall<GitConnectionTestResult>("git-repositories/test-connection", {
        method: "POST",
        body: JSON.stringify(data),
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

  const syncRepository = useMutation({
    mutationFn: (id: number) => apiCall<unknown>(`git/${id}/sync`, { method: "POST" }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Synced", description: "Repository cloned or pulled." });
    },
    onError: (error: Error) => {
      toast({ title: "Sync failed", description: error.message, variant: "destructive" });
    },
  });

  const removeAndSyncRepository = useMutation({
    mutationFn: (id: number) =>
      apiCall<unknown>(`git/${id}/remove-and-sync`, { method: "POST" }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Re-cloned", description: "Local copy removed and cloned fresh." });
    },
    onError: (error: Error) => {
      toast({ title: "Remove and re-clone failed", description: error.message, variant: "destructive" });
    },
  });

  return useMemo(
    () => ({
      createRepository,
      updateRepository,
      deleteRepository,
      testConnection,
      syncRepository,
      removeAndSyncRepository,
    }),
    [
      createRepository,
      updateRepository,
      deleteRepository,
      testConnection,
      syncRepository,
      removeAndSyncRepository,
    ],
  );
}
