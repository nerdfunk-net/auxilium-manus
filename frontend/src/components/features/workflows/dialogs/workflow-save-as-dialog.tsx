"use client";

import { useCallback, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
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
import { Switch } from "@/components/ui/switch";

import { useWorkflowCheckNameMutation } from "@/hooks/queries/use-workflow-check-name";

import { useWorkflowGitRepositories } from "../hooks/use-workflow-git-repositories";
import type { WorkflowVisibility } from "../types/workflow-persistence";

const saveAsSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(2000).optional(),
  folder: z.string().max(500).optional(),
  visibility: z.enum(["public", "private"]),
  is_version_controlled: z.boolean(),
});

type SaveAsFormValues = z.infer<typeof saveAsSchema>;

type SaveValues = {
  name: string;
  description?: string;
  folder?: string;
  visibility: WorkflowVisibility;
  is_version_controlled?: boolean;
};

interface WorkflowSaveAsDialogProps {
  open: boolean;
  defaultName?: string;
  defaultDescription?: string;
  defaultFolder?: string;
  defaultVisibility?: WorkflowVisibility;
  defaultIsVersionControlled?: boolean;
  isSaving?: boolean;
  onSave: (values: SaveValues) => void;
  onOverwrite: (values: SaveValues, existingId: number) => void;
  onClose: () => void;
}

export function WorkflowSaveAsDialog({
  open,
  defaultName = "",
  defaultDescription = "",
  defaultFolder = "/",
  defaultVisibility = "private",
  defaultIsVersionControlled = false,
  isSaving = false,
  onSave,
  onOverwrite,
  onClose,
}: WorkflowSaveAsDialogProps) {
  const checkName = useWorkflowCheckNameMutation();
  const { hasConfiguredGitRepository } = useWorkflowGitRepositories();
  const [pendingOverwrite, setPendingOverwrite] = useState<{
    message: string;
    existingId: number;
    values: SaveAsFormValues;
  } | null>(null);
  // The name is taken but the server named no workflow to overwrite: say why, offer nothing.
  const [unavailableMessage, setUnavailableMessage] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState(false);

  const clearNameConflict = useCallback(() => {
    setPendingOverwrite(null);
    setUnavailableMessage(null);
  }, []);

  const {
    register,
    handleSubmit,
    setValue,
    control,
    formState: { errors },
  } = useForm<SaveAsFormValues>({
    resolver: zodResolver(saveAsSchema),
    values: {
      name: defaultName,
      description: defaultDescription,
      folder: defaultFolder,
      visibility: defaultVisibility,
      is_version_controlled: defaultIsVersionControlled,
    },
  });

  const visibility = useWatch({ control, name: "visibility" });

  const onSubmit = useCallback(
    async (formValues: SaveAsFormValues) => {
      clearNameConflict();
      setIsChecking(true);
      // The name check treats an empty folder as "/", but an overwrite stores whatever it
      // is sent; sending the same normalised value keeps both on one folder.
      const values = { ...formValues, folder: formValues.folder || "/" };
      try {
        const check = await checkName.mutateAsync({
          name: values.name,
          folder: values.folder,
          visibility: values.visibility,
        });
        if (!check.available) {
          if (check.existing_id !== undefined) {
            setPendingOverwrite({
              message: check.message ?? "A workflow with this name already exists.",
              existingId: check.existing_id,
              values,
            });
          } else {
            setUnavailableMessage(check.message ?? "This name is not available.");
          }
          return;
        }
      } catch {
        // Ignore check errors and let the save attempt handle it
      } finally {
        setIsChecking(false);
      }
      onSave(values);
    },
    [checkName, onSave, clearNameConflict],
  );

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Save Workflow As</DialogTitle>
          <DialogDescription>Save the current workflow with a new name and location.</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4 py-2">
          <div className="grid gap-1.5">
            <Label htmlFor="wf-name">Name</Label>
            <Input
              id="wf-name"
              placeholder="My workflow"
              {...register("name", {
                onChange: () => clearNameConflict(),
              })}
            />
            {errors.name ? (
              <p className="text-xs text-destructive">{errors.name.message}</p>
            ) : null}
            {unavailableMessage ? (
              <p className="text-xs text-destructive">{unavailableMessage}</p>
            ) : null}
            {pendingOverwrite ? (
              <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs">
                <p className="text-destructive">{pendingOverwrite.message}</p>
                <div className="mt-2 flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    onClick={() => onOverwrite(pendingOverwrite.values, pendingOverwrite.existingId)}
                  >
                    Overwrite
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => clearNameConflict()}
                  >
                    Choose different name
                  </Button>
                </div>
              </div>
            ) : null}
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="wf-description">Description</Label>
            <Input
              id="wf-description"
              placeholder="Optional description"
              {...register("description")}
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="wf-folder">Folder</Label>
            <Input
              id="wf-folder"
              placeholder="/"
              {...register("folder", {
                onChange: () => clearNameConflict(),
              })}
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="wf-visibility">Visibility</Label>
            <Select
              value={visibility}
              onValueChange={(v) => {
                setValue("visibility", v as WorkflowVisibility);
                clearNameConflict();
              }}
            >
              <SelectTrigger id="wf-visibility">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="private">Private</SelectItem>
                <SelectItem value="public">Public</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center justify-between rounded-lg border px-3 py-2">
            <div>
              <Label className="mb-0" htmlFor="wf-save-as-version-controlled">
                Version controlled
              </Label>
              <p className="text-xs text-muted-foreground">
                {hasConfiguredGitRepository
                  ? "Every save is also committed to the configured Git repository."
                  : "Configure a Git repository in Settings → Git Repositories first."}
              </p>
            </div>
            <Controller
              control={control}
              name="is_version_controlled"
              render={({ field }) => (
                <Switch
                  id="wf-save-as-version-controlled"
                  checked={field.value}
                  disabled={!hasConfiguredGitRepository && !field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSaving || isChecking}>
              {isChecking ? "Checking…" : isSaving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
