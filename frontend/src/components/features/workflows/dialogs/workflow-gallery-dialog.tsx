"use client";

import { useCallback, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useTemplatesQuery } from "@/components/features/templates/hooks/use-templates-query";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { useWorkflowCheckNameMutation } from "@/hooks/queries/use-workflow-check-name";
import { useWorkflowGalleryListQuery } from "@/hooks/queries/use-workflow-gallery-query";
import { useWorkflowMutations } from "@/hooks/queries/use-workflow-mutations";

import { useWorkflowImportRemap } from "../hooks/use-workflow-import-remap";
import type { WorkflowExportFile } from "../types/workflow-export";
import { parseWorkflowExportFile } from "../utils/workflow-import";
import { WorkflowImportCredentialRemap } from "./workflow-import-credential-remap";
import { WorkflowImportReferenceRemap } from "./workflow-import-reference-remap";
import { executeWorkflowImportSave } from "./workflow-import-save";

const GALLERY_FOLDER = "Gallery";
const SOURCE_TYPES = ["nautobot", "mattermost", "batfish", "pyats"] as const;

interface WorkflowGalleryDialogProps {
  open: boolean;
  onClose: () => void;
}

type GalleryStep = "select" | "remap";

const EMPTY_CANVAS_NODES_LIST: Record<string, unknown>[][] = [];
const EMPTY_CREDENTIAL_REFS_LIST: WorkflowExportFile["credential_references"][] = [];

export function WorkflowGalleryDialog({ open, onClose }: WorkflowGalleryDialogProps) {
  const { data: listData, isLoading: listLoading } = useWorkflowGalleryListQuery({
    enabled: open,
  });
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { createWorkflow, updateWorkflow } = useWorkflowMutations();
  const checkName = useWorkflowCheckNameMutation();
  const { data: templatesData } = useTemplatesQuery({ enabled: open });

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [step, setStep] = useState<GalleryStep>("select");
  const [parsedFiles, setParsedFiles] = useState<WorkflowExportFile[] | null>(null);
  const [isFetchingFiles, setIsFetchingFiles] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(
    null,
  );

  const items = listData?.items ?? [];
  const existingTemplates = useMemo(
    () => templatesData?.templates ?? [],
    [templatesData?.templates],
  );

  const canvasNodesList = useMemo(
    () => parsedFiles?.map((file) => file.canvas_nodes) ?? EMPTY_CANVAS_NODES_LIST,
    [parsedFiles],
  );
  const credentialReferencesList = useMemo(
    () =>
      parsedFiles?.map((file) => file.credential_references) ??
      EMPTY_CREDENTIAL_REFS_LIST,
    [parsedFiles],
  );

  const remap = useWorkflowImportRemap({
    canvasNodesList,
    credentialReferencesList,
    enabled: open && step === "remap",
  });

  const toggleSelected = useCallback((id: string) => {
    setSelectedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const resetState = useCallback(() => {
    setSelectedIds(new Set());
    setStep("select");
    setParsedFiles(null);
    setIsFetchingFiles(false);
    setIsImporting(false);
    setProgress(null);
    remap.resetRemapState();
  }, [remap]);

  const handleClose = useCallback(() => {
    resetState();
    onClose();
  }, [resetState, onClose]);

  const handleProceedToRemap = useCallback(async () => {
    setIsFetchingFiles(true);
    try {
      const files = await Promise.all(
        [...selectedIds].map((id) =>
          apiCall<Record<string, unknown>>(`workflows/gallery/${id}`).then(
            (raw: Record<string, unknown>) => parseWorkflowExportFile(raw),
          ),
        ),
      );
      setParsedFiles(files);
      setStep("remap");
    } catch (error) {
      toast({
        title: "Could not load gallery workflows",
        description: error instanceof Error ? error.message : "Unknown error.",
        variant: "destructive",
      });
    } finally {
      setIsFetchingFiles(false);
    }
  }, [selectedIds, apiCall, toast]);

  const handleImport = useCallback(async () => {
    if (!parsedFiles) return;

    setIsImporting(true);
    setProgress({ done: 0, total: parsedFiles.length });
    const imported: string[] = [];
    const skipped: string[] = [];

    try {
      const { credentialRemap, gitRepositoryRemap, sourceRemaps } =
        remap.buildRemapArgs();

      for (const file of parsedFiles) {
        try {
          const check = await checkName.mutateAsync({
            name: file.name,
            folder: GALLERY_FOLDER,
            visibility: file.visibility,
          });
          if (!check.available) {
            skipped.push(file.name);
            continue;
          }

          await executeWorkflowImportSave({
            importFile: file,
            values: {
              name: file.name,
              description: file.description ?? "",
              folder: GALLERY_FOLDER,
              visibility: file.visibility,
            },
            existingTemplates,
            templatesToCreateCount: file.templates.length,
            credentialRemap,
            gitRepositoryRemap,
            sourceRemaps,
            apiCall,
            queryClient,
            createWorkflow: createWorkflow.mutateAsync,
            updateWorkflow: updateWorkflow.mutateAsync,
          });
          imported.push(file.name);
        } catch {
          skipped.push(file.name);
        } finally {
          setProgress((previous) =>
            previous ? { ...previous, done: previous.done + 1 } : previous,
          );
        }
      }

      toast({
        title: "Gallery import finished",
        description:
          `Imported ${imported.length} workflow${imported.length === 1 ? "" : "s"}` +
          (skipped.length > 0
            ? `; skipped ${skipped.length} (already exist): ${skipped.join(", ")}`
            : "."),
      });
      handleClose();
    } finally {
      setIsImporting(false);
      setProgress(null);
    }
  }, [
    parsedFiles,
    remap,
    checkName,
    existingTemplates,
    apiCall,
    queryClient,
    createWorkflow,
    updateWorkflow,
    toast,
    handleClose,
  ]);

  return (
    <Dialog open={open} onOpenChange={(isOpen: boolean) => !isOpen && handleClose()}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Workflow Gallery</DialogTitle>
          <DialogDescription>
            {step === "select"
              ? 'Select one or more example workflows to import into the "Gallery" folder.'
              : "Some selected workflows reference credentials, git repositories, or sources that don't exist here yet. Choose a replacement for each before importing."}
          </DialogDescription>
        </DialogHeader>

        {step === "select" ? (
          <>
            <div className="flex-1 space-y-2 overflow-y-auto px-1 py-1">
              {listLoading ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : items.length === 0 ? (
                <p className="text-sm italic text-muted-foreground">
                  No example workflows available.
                </p>
              ) : (
                items.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => toggleSelected(item.id)}
                    className="flex w-full cursor-pointer items-start gap-3 rounded-md border p-3 text-left hover:bg-muted/50"
                  >
                    <span onClick={(e) => e.stopPropagation()}>
                      <Checkbox
                        className="mt-0.5"
                        checked={selectedIds.has(item.id)}
                        onCheckedChange={() => toggleSelected(item.id)}
                      />
                    </span>
                    <span className="grid gap-0.5">
                      <span className="text-sm font-medium">{item.name}</span>
                      {item.description ? (
                        <span className="text-xs text-muted-foreground">
                          {item.description}
                        </span>
                      ) : null}
                    </span>
                  </div>
                ))
              )}
            </div>
            <DialogFooter className="shrink-0 pt-4">
              <Button type="button" variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <Button
                type="button"
                disabled={selectedIds.size === 0 || isFetchingFiles}
                onClick={() => void handleProceedToRemap()}
              >
                {isFetchingFiles ? "Loading…" : `Import Selected (${selectedIds.size})`}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <div className="flex-1 space-y-4 overflow-y-auto px-1 py-1">
              <p className="text-xs text-muted-foreground">
                Importing: {parsedFiles?.map((file) => file.name).join(", ")}
              </p>

              {remap.credential.requirements.length > 0 ? (
                <WorkflowImportCredentialRemap
                  requirements={remap.credential.requirements}
                  credentials={remap.credential.credentials}
                  value={remap.credential.value}
                  onChange={remap.credential.onChange}
                  isLoading={remap.credential.isLoading}
                />
              ) : null}

              {remap.gitRepository.requirements.length > 0 ? (
                <WorkflowImportReferenceRemap
                  title="Git repository mapping"
                  description="These workflows reference a git repository that doesn't exist here. Choose a replacement before importing."
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

              {SOURCE_TYPES.map((sourceType) => {
                const section = remap.sources[sourceType];
                if (section.requirements.length === 0) return null;
                const label = sourceType.charAt(0).toUpperCase() + sourceType.slice(1);
                return (
                  <WorkflowImportReferenceRemap
                    key={sourceType}
                    title={`${label} source mapping`}
                    description={`These workflows reference a ${label} source that isn't configured here. Choose a replacement before importing.`}
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
              })}
            </div>
            <DialogFooter className="shrink-0 pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={() => setStep("select")}
                disabled={isImporting}
              >
                Back
              </Button>
              <Button
                type="button"
                disabled={
                  isImporting || (remap.hasAnyRequirements && !remap.allSelected)
                }
                onClick={() => void handleImport()}
              >
                {isImporting
                  ? `Importing (${progress?.done ?? 0}/${progress?.total ?? 0})…`
                  : "Import"}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
