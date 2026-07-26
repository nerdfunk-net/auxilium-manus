"use client";

import { useCallback, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

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
import { useToast } from "@/hooks/use-toast";
import { useWorkflowMutations } from "@/hooks/queries/use-workflow-mutations";

import type { WorkflowVisibility } from "../types/workflow-persistence";
import type { WorkflowExportFile } from "../types/workflow-export";
import { parseWorkflowExportFile } from "../utils/workflow-import";

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
  const { toast } = useToast();

  const [importFile, setImportFile] = useState<WorkflowExportFile | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [pendingOverwrite, setPendingOverwrite] = useState<{
    message: string;
    existingId: number;
    values: ImportFormValues;
  } | null>(null);
  const [isChecking, setIsChecking] = useState(false);

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
  const isSaving = createWorkflow.isPending || updateWorkflow.isPending;

  const resetState = useCallback(() => {
    setImportFile(null);
    setParseError(null);
    setPendingOverwrite(null);
    setIsChecking(false);
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
        reset({
          name: parsed.name,
          description: parsed.description ?? "",
          folder: parsed.folder ?? "/",
          visibility: parsed.visibility,
        });
      } catch (err) {
        setImportFile(null);
        setParseError(
          err instanceof Error
            ? err.message
            : "Could not read the selected file.",
        );
      }
    };
    input.click();
  }, [reset]);

  const performSave = useCallback(
    (values: ImportFormValues, overwriteId?: number) => {
      if (!importFile) return;
      const payload = {
        name: values.name,
        description: values.description,
        folder: values.folder || "/",
        visibility: values.visibility,
        canvas_nodes: importFile.canvas_nodes,
        canvas_edges: importFile.canvas_edges,
        canvas_groups: importFile.canvas_groups,
      };

      const onSuccess = () => {
        toast({
          title: "Import complete",
          description: `"${values.name}" was imported.`,
        });
        handleClose();
      };
      const onError = (error: Error) => {
        toast({
          title: "Import failed",
          description: error.message,
          variant: "destructive",
        });
      };

      if (overwriteId !== undefined) {
        updateWorkflow.mutate(
          { id: overwriteId, data: payload },
          { onSuccess, onError },
        );
      } else {
        createWorkflow.mutate(payload, { onSuccess, onError });
      }
    },
    [importFile, createWorkflow, updateWorkflow, toast, handleClose],
  );

  const onSubmit = useCallback(
    async (values: ImportFormValues) => {
      setPendingOverwrite(null);
      setIsChecking(true);
      try {
        const folder = values.folder || "/";
        const params = new URLSearchParams({
          name: values.name,
          folder,
          visibility: values.visibility,
        });
        const res = await fetch(
          `/api/proxy/workflows/check-name?${params.toString()}`,
          {
            credentials: "include",
          },
        );
        if (res.ok) {
          const check = (await res.json()) as {
            available: boolean;
            message?: string;
            existing_id?: number;
          };
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
        }
      } catch {
        // Ignore check errors and let the save attempt handle it
      } finally {
        setIsChecking(false);
      }
      performSave(values);
    },
    [performSave],
  );

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <DialogContent className="sm:max-w-md">
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
                      performSave(
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

          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!importFile || isSaving || isChecking}
            >
              {isChecking ? "Checking…" : isSaving ? "Importing…" : "Import"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
