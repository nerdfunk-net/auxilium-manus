"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo } from "react";

import { useToast } from "@/hooks/use-toast";

import { TEMPLATE_CATEGORY } from "../constants";
import type { TemplateType, TemplateVariableRecord } from "../types";
import {
  buildTemplateExportFile,
  downloadTemplateExportFile,
} from "../utils/template-export";
import { useTemplateMutations } from "./use-template-mutations";
import type { useTemplateVariables } from "./use-template-variables";

type TemplateVariablesManager = ReturnType<typeof useTemplateVariables>;

interface UseTemplateEditorSaveOptions {
  name: string;
  description: string;
  templateType: TemplateType;
  content: string;
  cleanedCommands: string[];
  useTextfsm: boolean;
  attributes: string[];
  credentialId: string;
  variableManager: TemplateVariablesManager;
  isEditMode: boolean;
  templateId: number | null;
}

function buildCustomVariables(
  variables: TemplateVariablesManager["variables"],
): Record<string, TemplateVariableRecord> {
  const result: Record<string, TemplateVariableRecord> = {};
  for (const variable of variables) {
    if (variable.name && !variable.isAutoFilled) {
      result[variable.name] = {
        value: variable.value,
        type: variable.type || "custom",
      };
    }
  }
  return result;
}

export function useTemplateEditorSave({
  name,
  description,
  templateType,
  content,
  cleanedCommands,
  useTextfsm,
  attributes,
  credentialId,
  variableManager,
  isEditMode,
  templateId,
}: UseTemplateEditorSaveOptions) {
  const router = useRouter();
  const { toast } = useToast();
  const { createTemplate, updateTemplate } = useTemplateMutations();

  const handleExport = useCallback(() => {
    if (!name.trim()) {
      toast({
        title: "Validation error",
        description: "Template name is required before export",
        variant: "destructive",
      });
      return;
    }

    const envelope = buildTemplateExportFile({
      name: name.trim(),
      description: description || null,
      template_type: templateType,
      category: TEMPLATE_CATEGORY,
      content,
      variables: buildCustomVariables(variableManager.variables),
      pre_run_commands: cleanedCommands,
      pre_run_use_textfsm: useTextfsm,
      nautobot_attributes: attributes,
    });
    downloadTemplateExportFile(envelope);
    toast({
      title: "Export complete",
      description: "Template JSON was downloaded.",
    });
  }, [
    name,
    description,
    templateType,
    content,
    cleanedCommands,
    useTextfsm,
    attributes,
    variableManager.variables,
    toast,
  ]);

  const handleSave = useCallback(async () => {
    if (!name.trim()) {
      toast({
        title: "Validation error",
        description: "Template name is required",
        variant: "destructive",
      });
      return;
    }

    const payload = {
      name: name.trim(),
      description: description || null,
      template_type: templateType,
      category: TEMPLATE_CATEGORY,
      content,
      variables: buildCustomVariables(variableManager.variables),
      pre_run_commands: cleanedCommands,
      pre_run_use_textfsm: useTextfsm,
      nautobot_attributes: attributes,
      credential_id: credentialId !== "none" ? Number(credentialId) : null,
    };

    try {
      if (isEditMode && templateId !== null) {
        await updateTemplate.mutateAsync({ templateId, payload });
      } else {
        await createTemplate.mutateAsync(payload);
      }
      router.push("/templates");
    } catch {
      // error toast handled by mutation hooks
    }
  }, [
    name,
    description,
    templateType,
    content,
    cleanedCommands,
    useTextfsm,
    attributes,
    credentialId,
    variableManager.variables,
    isEditMode,
    templateId,
    updateTemplate,
    createTemplate,
    router,
    toast,
  ]);

  const isSaving = createTemplate.isPending || updateTemplate.isPending;

  return useMemo(
    () => ({
      handleSave,
      handleExport,
      isSaving,
    }),
    [handleSave, handleExport, isSaving],
  );
}
