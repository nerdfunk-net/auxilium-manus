"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

import type {
  Template,
  TemplateCreatePayload,
  TemplateUpdatePayload,
} from "../types";

export function useTemplateMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.templates.all });
  };

  const createTemplate = useMutation({
    mutationFn: (payload: TemplateCreatePayload) =>
      apiCall<Template>("templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Template created." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const updateTemplate = useMutation({
    mutationFn: ({
      templateId,
      payload,
    }: {
      templateId: number;
      payload: TemplateUpdatePayload;
    }) =>
      apiCall<Template>(`templates/${templateId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Template updated." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const deleteTemplate = useMutation({
    mutationFn: (templateId: number) =>
      apiCall<void>(`templates/${templateId}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Deleted", description: "Template deleted." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  return { createTemplate, updateTemplate, deleteTemplate };
}
