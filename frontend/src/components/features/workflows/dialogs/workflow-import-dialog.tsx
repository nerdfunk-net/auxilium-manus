"use client";

import { useCallback, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";

import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import { useTemplatesQuery } from "@/components/features/templates/hooks/use-templates-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { useWorkflowCheckNameMutation } from "@/hooks/queries/use-workflow-check-name";
import { useWorkflowMutations } from "@/hooks/queries/use-workflow-mutations";
import { useAuthStore } from "@/lib/auth-store";

import type { WorkflowExportFile } from "../types/workflow-export";
import {
  buildCredentialRemapRequirements,
  collectCredentialReferencesFromCanvas,
} from "../utils/workflow-import";
import { WorkflowImportCredentialRemap } from "./workflow-import-credential-remap";
import { WorkflowImportFileField } from "./workflow-import-file-field";
import { WorkflowImportFormFooter } from "./workflow-import-form-footer";
import { WorkflowImportMetadataFields } from "./workflow-import-metadata-fields";
import { executeWorkflowImportSave } from "./workflow-import-save";
import {
  workflowImportSchema,
  type WorkflowImportFormValues,
} from "./workflow-import-schema";

type ImportFormValues = WorkflowImportFormValues;

interface WorkflowImportDialogProps {
  open: boolean;
  onClose: () => void;
}

export function WorkflowImportDialog({
  open,
  onClose,
}: WorkflowImportDialogProps) {
  const { createWorkflow, updateWorkflow } = useWorkflowMutations();
  const checkName = useWorkflowCheckNameMutation();
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const currentUsername = useAuthStore((state) => state.user?.username ?? "");
  const { data: credentialsData, isLoading: credentialsLoading } =
    useCredentialsQuery({ enabled: open });
  const { data: templatesData, isLoading: templatesLoading } = useTemplatesQuery({
    enabled: open,
  });

  const [importFile, setImportFile] = useState<WorkflowExportFile | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [pendingOverwrite, setPendingOverwrite] = useState<{
    message: string;
    existingId: number;
    values: ImportFormValues;
  } | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [isResolvingTemplates, setIsResolvingTemplates] = useState(false);
  const [credentialRemap, setCredentialRemap] = useState<
    Record<string, string>
  >({});

  const {
    register,
    handleSubmit,
    setValue,
    control,
    reset,
    formState: { errors },
  } = useForm<ImportFormValues>({
    resolver: zodResolver(workflowImportSchema),
    defaultValues: {
      name: "",
      description: "",
      folder: "/",
      visibility: "private",
    },
  });

  const visibility = useWatch({ control, name: "visibility" });
  const isSaving =
    createWorkflow.isPending ||
    updateWorkflow.isPending ||
    isResolvingTemplates;

  const visibleCredentials = useMemo(
    () => credentialsData?.credentials ?? [],
    [credentialsData?.credentials],
  );

  const existingTemplates = useMemo(
    () => templatesData?.templates ?? [],
    [templatesData?.templates],
  );

  const sshCredentials = useMemo(
    () =>
      visibleCredentials.filter(
        (credential) =>
          credential.type === "ssh" && credential.status !== "expired",
      ),
    [visibleCredentials],
  );

  const canvasCredentialNames = useMemo(
    () =>
      importFile
        ? collectCredentialReferencesFromCanvas(importFile.canvas_nodes)
        : [],
    [importFile],
  );

  const remapRequirements = useMemo(() => {
    if (!importFile || credentialsLoading) return [];
    return buildCredentialRemapRequirements(
      importFile.credential_references,
      importFile.canvas_nodes,
      visibleCredentials,
      currentUsername,
    );
  }, [importFile, credentialsLoading, visibleCredentials, currentUsername]);

  const showCredentialMapping =
    Boolean(importFile) &&
    (credentialsLoading
      ? canvasCredentialNames.length > 0
      : remapRequirements.length > 0);

  const templateImportSummary = useMemo(() => {
    if (!importFile || templatesLoading) {
      return { reuse: [] as string[], create: [] as string[] };
    }
    const existingNames = new Set(existingTemplates.map((t) => t.name));
    const reuse: string[] = [];
    const create: string[] = [];
    for (const template of importFile.templates) {
      if (existingNames.has(template.name)) {
        reuse.push(template.name);
      } else {
        create.push(template.name);
      }
    }
    return { reuse, create };
  }, [importFile, existingTemplates, templatesLoading]);

  const allRemapsSelected = useMemo(
    () =>
      remapRequirements.every((requirement) =>
        Boolean(credentialRemap[requirement.name]?.trim()),
      ),
    [remapRequirements, credentialRemap],
  );

  const resetState = useCallback(() => {
    setImportFile(null);
    setParseError(null);
    setPendingOverwrite(null);
    setIsChecking(false);
    setIsResolvingTemplates(false);
    setCredentialRemap({});
    reset({ name: "", description: "", folder: "/", visibility: "private" });
  }, [reset]);

  const handleClose = useCallback(() => {
    resetState();
    onClose();
  }, [resetState, onClose]);

  const handleFileParsed = useCallback(
    (parsed: WorkflowExportFile) => {
      setImportFile(parsed);
      setParseError(null);
      setPendingOverwrite(null);
      setCredentialRemap({});
      reset({
        name: parsed.name,
        description: parsed.description ?? "",
        folder: parsed.folder ?? "/",
        visibility: parsed.visibility,
      });
    },
    [reset],
  );

  const handleFileError = useCallback((message: string) => {
    setImportFile(null);
    setCredentialRemap({});
    setParseError(message);
  }, []);

  const handleRemapChange = useCallback((oldName: string, newName: string) => {
    setCredentialRemap((previous) => ({ ...previous, [oldName]: newName }));
  }, []);

  const buildRemapMap = useCallback(() => {
    const map = new Map<string, string>();
    for (const requirement of remapRequirements) {
      const selected = credentialRemap[requirement.name]?.trim();
      if (selected) {
        map.set(requirement.name, selected);
      }
    }
    return map;
  }, [remapRequirements, credentialRemap]);

  const performSave = useCallback(
    async (values: ImportFormValues, overwriteId?: number) => {
      if (!importFile) return;

      setIsResolvingTemplates(true);
      try {
        await executeWorkflowImportSave({
          importFile,
          values,
          overwriteId,
          existingTemplates,
          templatesToCreateCount: templateImportSummary.create.length,
          credentialRemap: buildRemapMap(),
          apiCall,
          queryClient,
          createWorkflow: createWorkflow.mutateAsync,
          updateWorkflow: updateWorkflow.mutateAsync,
        });

        toast({
          title: "Import complete",
          description: `"${values.name}" was imported.`,
        });
        handleClose();
      } catch (error) {
        toast({
          title: "Import failed",
          description:
            error instanceof Error
              ? error.message
              : "Could not import workflow.",
          variant: "destructive",
        });
      } finally {
        setIsResolvingTemplates(false);
      }
    },
    [
      importFile,
      existingTemplates,
      templateImportSummary.create.length,
      apiCall,
      queryClient,
      buildRemapMap,
      createWorkflow,
      updateWorkflow,
      toast,
      handleClose,
    ],
  );

  const onSubmit = useCallback(
    async (values: ImportFormValues) => {
      if (remapRequirements.length > 0 && !allRemapsSelected) {
        toast({
          title: "Credentials required",
          description:
            "Select a replacement credential for each referenced credential before importing.",
          variant: "destructive",
        });
        return;
      }

      setPendingOverwrite(null);
      setIsChecking(true);
      try {
        const folder = values.folder || "/";
        const check = await checkName.mutateAsync({
          name: values.name,
          folder,
          visibility: values.visibility,
        });
        if (!check.available) {
          if (check.existing_id !== undefined) {
            setPendingOverwrite({
              message:
                check.message ?? "A workflow with this name already exists.",
              existingId: check.existing_id,
              values,
            });
          }
          return;
        }
      } catch {
        // Ignore check errors and let the save attempt handle it
      } finally {
        setIsChecking(false);
      }
      await performSave(values);
    },
    [checkName, performSave, remapRequirements.length, allRemapsSelected, toast],
  );

  const showTemplateSummary =
    Boolean(importFile) &&
    (importFile?.templates.length ?? 0) > 0 &&
    !templatesLoading;

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Import Workflow</DialogTitle>
          <DialogDescription>
            Import a workflow from a previously exported JSON file.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4 py-2">
          <WorkflowImportFileField
            importFile={importFile}
            parseError={parseError}
            onParsed={handleFileParsed}
            onError={handleFileError}
          />

          <WorkflowImportMetadataFields
            importFile={importFile}
            register={register}
            errors={errors}
            visibility={visibility}
            setValue={setValue}
            onClearPendingOverwrite={() => setPendingOverwrite(null)}
            pendingOverwrite={pendingOverwrite}
            onConfirmOverwrite={() =>
              pendingOverwrite &&
              void performSave(
                pendingOverwrite.values,
                pendingOverwrite.existingId,
              )
            }
            showTemplateSummary={showTemplateSummary}
            templateImportSummary={templateImportSummary}
          />

          {showCredentialMapping ? (
            <WorkflowImportCredentialRemap
              requirements={remapRequirements}
              credentials={sshCredentials}
              value={credentialRemap}
              onChange={handleRemapChange}
              isLoading={credentialsLoading}
            />
          ) : null}

          <WorkflowImportFormFooter
            onClose={handleClose}
            disabled={
              !importFile ||
              isSaving ||
              isChecking ||
              credentialsLoading ||
              templatesLoading ||
              (remapRequirements.length > 0 && !allRemapsSelected)
            }
            submitLabel={
              isChecking
                ? "Checking…"
                : isResolvingTemplates
                  ? "Importing templates…"
                  : isSaving
                    ? "Importing…"
                    : "Import"
            }
          />
        </form>
      </DialogContent>
    </Dialog>
  );
}
