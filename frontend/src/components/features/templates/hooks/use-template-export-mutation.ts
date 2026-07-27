"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

import type { Template } from "../types";
import {
  buildTemplateExportFile,
  downloadTemplateExportFile,
} from "../utils/template-export";

export function useTemplateExportMutation() {
  const { apiCall } = useApi();
  const { toast } = useToast();

  return useMutation({
    mutationFn: async (templateId: number) => {
      const template = await apiCall<Template>(`templates/${templateId}`);
      const envelope = buildTemplateExportFile(template);
      downloadTemplateExportFile(envelope);
    },
    onSuccess: () => {
      toast({
        title: "Export complete",
        description: "Template JSON was downloaded.",
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Export failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}
