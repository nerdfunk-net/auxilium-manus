"use client";

import { useCallback, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { CredentialVisibilityBadge } from "@/components/features/settings/credentials/components/credential-visibility-badge";
import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import type { CredentialVisibility } from "@/components/features/settings/credentials/types";
import { useTemplatesQuery } from "@/components/features/templates/hooks/use-templates-query";
import type { Template } from "@/components/features/templates/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { useWorkflowCheckNameMutation } from "@/hooks/queries/use-workflow-check-name";
import { useWorkflowMutations } from "@/hooks/queries/use-workflow-mutations";
import { useAuthStore } from "@/lib/auth-store";
import { queryKeys } from "@/lib/query-keys";

import type { WorkflowExportFile } from "../types/workflow-export";
import type { WorkflowVisibility } from "../types/workflow-persistence";
import {
  applyCredentialRemap,
  applyTemplateIdRemap,
  buildCredentialRemapRequirements,
  collectCredentialReferencesFromCanvas,
  parseWorkflowExportFile,
  resolveWorkflowTemplatesOnImport,
} from "../utils/workflow-import";

const importSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(2000).optional(),
  folder: z.string().max(500).optional(),
  visibility: z.enum(["public", "private"]),
});

type ImportFormValues = z.infer<typeof importSchema>;

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
    resolver: zodResolver(importSchema),
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

  const handleChooseFile = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,application/json";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const parsed = parseWorkflowExportFile(JSON.parse(text));
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
      } catch (err) {
        setImportFile(null);
        setCredentialRemap({});
        setParseError(
          err instanceof Error
            ? err.message
            : "Could not read the selected file.",
        );
      }
    };
    input.click();
  }, [reset]);

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
        const templateIdRemap = await resolveWorkflowTemplatesOnImport({
          exportedTemplates: importFile.templates,
          existingTemplates,
          createTemplate: (payload) =>
            apiCall<Template>("templates", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            }),
        });

        if (templateImportSummary.create.length > 0) {
          await queryClient.invalidateQueries({
            queryKey: queryKeys.templates.all,
          });
        }

        let canvasNodes = applyCredentialRemap(
          importFile.canvas_nodes,
          buildRemapMap(),
        );
        canvasNodes = applyTemplateIdRemap(canvasNodes, templateIdRemap);

        const payload = {
          name: values.name,
          description: values.description,
          folder: values.folder || "/",
          visibility: values.visibility,
          canvas_nodes: canvasNodes,
          canvas_edges: importFile.canvas_edges,
          canvas_groups: importFile.canvas_groups,
          static_attributes: importFile.static_attributes,
        };

        if (overwriteId !== undefined) {
          await updateWorkflow.mutateAsync({ id: overwriteId, data: payload });
        } else {
          await createWorkflow.mutateAsync(payload);
        }

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
          <div className="grid gap-1.5">
            <Label>File</Label>
            <Button type="button" variant="outline" onClick={handleChooseFile}>
              {importFile ? "Choose a different file…" : "Choose file…"}
            </Button>
            {importFile ? (
              <p className="text-xs text-muted-foreground">
                Selected file parsed successfully.
              </p>
            ) : null}
            {parseError ? (
              <p className="text-xs text-destructive">{parseError}</p>
            ) : null}
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="import-name">Name</Label>
            <Input
              id="import-name"
              placeholder="My workflow"
              disabled={!importFile}
              {...register("name", {
                onChange: () => setPendingOverwrite(null),
              })}
            />
            {errors.name ? (
              <p className="text-xs text-destructive">{errors.name.message}</p>
            ) : null}
            {pendingOverwrite ? (
              <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs">
                <p className="text-destructive">{pendingOverwrite.message}</p>
                <div className="mt-2 flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    onClick={() =>
                      void performSave(
                        pendingOverwrite.values,
                        pendingOverwrite.existingId,
                      )
                    }
                  >
                    Overwrite
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => setPendingOverwrite(null)}
                  >
                    Choose different name
                  </Button>
                </div>
              </div>
            ) : null}
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="import-description">Description</Label>
            <Input
              id="import-description"
              placeholder="Optional description"
              disabled={!importFile}
              {...register("description")}
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="import-folder">Folder</Label>
            <Input
              id="import-folder"
              placeholder="/"
              disabled={!importFile}
              {...register("folder", {
                onChange: () => setPendingOverwrite(null),
              })}
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="import-visibility">Visibility</Label>
            <Select
              value={visibility}
              onValueChange={(v) => {
                setValue("visibility", v as WorkflowVisibility);
                setPendingOverwrite(null);
              }}
              disabled={!importFile}
            >
              <SelectTrigger id="import-visibility">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="private">Private</SelectItem>
                <SelectItem value="public">Public</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {showTemplateSummary ? (
            <div className="grid gap-1.5 rounded-md border p-3 text-xs">
              <Label>Templates</Label>
              {templateImportSummary.reuse.length > 0 ? (
                <p className="text-muted-foreground">
                  Reuse existing: {templateImportSummary.reuse.join(", ")}
                </p>
              ) : null}
              {templateImportSummary.create.length > 0 ? (
                <p className="text-muted-foreground">
                  Will import: {templateImportSummary.create.join(", ")}
                </p>
              ) : null}
            </div>
          ) : null}

          {showCredentialMapping ? (
            <div className="grid gap-3 rounded-md border p-3">
              <div className="grid gap-1">
                <Label>Credential mapping</Label>
                <p className="text-xs text-muted-foreground">
                  Some credentials belong to another user or are not available
                  in your vault. Choose a replacement for each before importing.
                </p>
              </div>
              {credentialsLoading ? (
                <p className="text-xs text-muted-foreground">
                  Loading credentials…
                </p>
              ) : sshCredentials.length === 0 ? (
                <p className="text-xs text-warning-foreground">
                  No SSH credentials available. Add credentials in Settings →
                  Credentials first.
                </p>
              ) : (
                remapRequirements.map((requirement) => (
                  <div key={requirement.name} className="grid gap-1.5">
                    <div className="flex flex-wrap items-center gap-1.5 text-xs">
                      <span className="font-mono font-medium">
                        {requirement.name}
                      </span>
                      {requirement.visibility === "unknown" ? (
                        <Badge
                          className="h-4 rounded px-1 text-[10px]"
                          variant="secondary"
                        >
                          Unknown
                        </Badge>
                      ) : (
                        <CredentialVisibilityBadge
                          className="h-4 rounded px-1 text-[10px]"
                          visibility={
                            requirement.visibility as CredentialVisibility
                          }
                        />
                      )}
                      {requirement.owner_username ? (
                        <span className="text-muted-foreground">
                          owner: {requirement.owner_username}
                        </span>
                      ) : null}
                    </div>
                    <Select
                      value={credentialRemap[requirement.name] ?? ""}
                      onValueChange={(value) =>
                        handleRemapChange(requirement.name, value)
                      }
                    >
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="Select replacement credential" />
                      </SelectTrigger>
                      <SelectContent>
                        {sshCredentials.map((credential) => (
                          <SelectItem
                            key={credential.id}
                            value={credential.name}
                          >
                            {credential.name} ({credential.username}) ·{" "}
                            {credential.visibility === "global"
                              ? "Global"
                              : "Private"}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ))
              )}
            </div>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                !importFile ||
                isSaving ||
                isChecking ||
                credentialsLoading ||
                templatesLoading ||
                (remapRequirements.length > 0 && !allRemapsSelected)
              }
            >
              {isChecking
                ? "Checking…"
                : isResolvingTemplates
                  ? "Importing templates…"
                  : isSaving
                    ? "Importing…"
                    : "Import"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
