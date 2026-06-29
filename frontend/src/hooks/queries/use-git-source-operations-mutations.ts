"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

export function usePullGitSourceMutation() {
  const { apiCall } = useApi();
  const { toast } = useToast();

  return useMutation({
    mutationFn: async (gitSourceId: string) =>
      apiCall<{ success: boolean; message: string }>("sources/git/pull", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ git_source_id: gitSourceId }),
      }),
    onSuccess: (data) => {
      toast({ title: "Pull successful", description: data?.message });
    },
    onError: (error: Error) => {
      toast({
        title: "Pull failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}

export function useRemoveAndCloneGitSourceMutation() {
  const { apiCall } = useApi();
  const { toast } = useToast();

  return useMutation({
    mutationFn: async (gitSourceId: string) =>
      apiCall<{ success: boolean; message: string }>(
        "sources/git/remove-and-clone",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ git_source_id: gitSourceId }),
        },
      ),
    onSuccess: (data) => {
      toast({ title: "Remove and clone successful", description: data?.message });
    },
    onError: (error: Error) => {
      toast({
        title: "Remove and clone failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}
