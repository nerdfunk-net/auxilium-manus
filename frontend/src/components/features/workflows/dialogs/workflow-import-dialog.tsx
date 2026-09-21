"use client";

import { useCallback, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";

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

import { useWorkflowImportRemap } from "../hooks/use-workflow-import-remap";
import type { WorkflowExportFile } from "../types/workflow-export";
import { WorkflowImportCredentialRemap } from "./workflow-import-credential-remap";
import { WorkflowImportFileField } from "./workflow-import-file-field";
import { WorkflowImportFormFooter } from "./workflow-import-form-footer";
import { WorkflowImportMetadataFields } from "./workflow-import-metadata-fields";
import { WorkflowImportReferenceRemap } from "./workflow-import-reference-remap";
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

const EMPTY_CANVAS_NODES_LIST: Record<string, unknown>[][] = [];
const EMPTY_CREDENTIAL_REFS_LIST: WorkflowExportFile["credential_references"][] = [];

export function WorkflowImportDialog({
  open,
  onClose,
}: WorkflowImportDialogProps) {
  const { createWorkflow, updateWorkflow } = useWorkflowMutations();
  const checkName = useWorkflowCheckNameMutation();
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();
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

  const canvasNodesList = useMemo(
    () => (importFile ? [importFile.canvas_nodes] : EMPTY_CANVAS_NODES_LIST),
    [importFile],
  );
  const credentialReferencesList = useMemo(
    () =>
      importFile ? [importFile.credential_references] : EMPTY_CREDENTIAL_REFS_LIST,
    [importFile],
  );

  const remap = useWorkflowImportRemap({
    canvasNodesList,
    credentialReferencesList,
    enabled: open && Boolean(importFile),
  });

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

  const existingTemplates = useMemo(
    () => templatesData?.templates ?? [],
    [templatesData?.templates],
  );

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

  const resetState = useCallback(() => {
    setImportFile(null);
    setParseError(null);
    setPendingOverwrite(null);
    setIsChecking(false);
    setIsResolvingTemplates(false);
    remap.resetRemapState();
    reset({ name: "", description: "", folder: "/", visibility: "private" });
  }, [reset, remap]);

  const handleClose = useCallback(() => {
    resetState();
    onClose();
  }, [resetState, onClose]);

  const handleFileParsed = useCallback(
    (parsed: WorkflowExportFile) => {
      setImportFile(parsed);
      setParseError(null);
      setPendingOverwrite(null);
      remap.resetRemapState();
      reset({
        name: parsed.name,
        description: parsed.description ?? "",
        folder: parsed.folder ?? "/",
        visibility: parsed.visibility,
      });
    },
    [reset, remap],
  );

  const handleFileError = useCallback(
    (message: string) => {
      setImportFile(null);
      remap.resetRemapState();
      setParseError(message);
    },
    [remap],
  );

  const performSave = useCallback(
    async (values: ImportFormValues, overwriteId?: number) => {
      if (!importFile) return;

      setIsResolvingTemplates(true);
      try {
        const { credentialRemap, gitRepositoryRemap, sourceRemaps } =
          remap.buildRemapArgs();
        await executeWorkflowImportSave({
          importFile,
          values,
          overwriteId,
          existingTemplates,
          templatesToCreateCount: templateImportSummary.create.length,
          credentialRemap,
          gitRepositoryRemap,
          sourceRemaps,
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
      remap,
      apiCall,
      queryClient,
      createWorkflow,
      updateWorkflow,
      toast,
      handleClose,
    ],
  );

  const onSubmit = useCallback(
    async (values: ImportFormValues) => {
      if (remap.hasAnyRequirements && !remap.allSelected) {
        toast({
          title: "References required",
          description:
            "Select a replacement for each referenced credential, git repository, or source before importing.",
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
    [checkName, performSave, remap.hasAnyRequirements, remap.allSelected, toast],
  );

  const showTemplateSummary =
    Boolean(importFile) &&
    (importFile?.templates.length ?? 0) > 0 &&
    !templatesLoading;

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Import Workflow</DialogTitle>
          <DialogDescription>
            Import a workflow from a previously exported JSON file.
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={handleSubmit(onSubmit)}
          className="flex min-h-0 flex-1 flex-col"
        >
          <div className="flex-1 space-y-4 overflow-y-auto px-1 py-1">
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

            {importFile && remap.credential.requirements.length > 0 ? (
              <WorkflowImportCredentialRemap
                requirements={remap.credential.requirements}
                credentials={remap.credential.credentials}
                value={remap.credential.value}
                onChange={remap.credential.onChange}
                isLoading={remap.credential.isLoading}
              />
            ) : null}

            {importFile && remap.gitRepository.requirements.length > 0 ? (
              <WorkflowImportReferenceRemap
                title="Git repository mapping"
                description="This workflow references a git repository that doesn't exist here. Choose a replacement before importing."
                requirements={remap.gitRepository.requirements.map((r) => ({
                  key: String(r.id),
                  label: `Repository #${r.id}`,
                }))}
                options={remap.gitRepository.options}
                value={remap.gitRepository.value}
                onChange={remap.gitRepository.onChange}
                isLoading={remap.gitRepository.isLoading}
                emptyMessage="No git repositories configured. Add one in Settings → Git Repositories first."
              />
            ) : null}

            {importFile &&
              (["nautobot", "mattermost", "batfish", "pyats"] as const).map(
                (sourceType) => {
                  const section = remap.sources[sourceType];
                  if (section.requirements.length === 0) return null;
                  const label =
                    sourceType.charAt(0).toUpperCase() + sourceType.slice(1);
                  return (
                    <WorkflowImportReferenceRemap
                      key={sourceType}
                      title={`${label} source mapping`}
                      description={`This workflow references a ${label} source that isn't configured here. Choose a replacement before importing.`}
                      requirements={section.requirements.map((r) => ({
                        key: r.sourceId,
                        label: r.sourceId,
                      }))}
                      options={section.options}
                      value={section.value}
                      onChange={section.onChange}
                      isLoading={section.isLoading}
                      emptyMessage={`No ${label} sources configured. Add one in Settings → Sources first.`}
                    />
                  );
                },
              )}
          </div>

          <WorkflowImportFormFooter
            onClose={handleClose}
            disabled={
              !importFile ||
              isSaving ||
              isChecking ||
              templatesLoading ||
              (remap.hasAnyRequirements && !remap.allSelected)
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
