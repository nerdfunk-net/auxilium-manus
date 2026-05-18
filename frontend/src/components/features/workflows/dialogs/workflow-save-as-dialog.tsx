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

import type { WorkflowVisibility } from "../types/workflow-persistence";

const saveAsSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(2000).optional(),
  folder: z.string().max(500).optional(),
  visibility: z.enum(["public", "private"]),
});

type SaveAsFormValues = z.infer<typeof saveAsSchema>;

interface WorkflowSaveAsDialogProps {
  open: boolean;
  defaultName?: string;
  defaultDescription?: string;
  defaultFolder?: string;
  defaultVisibility?: WorkflowVisibility;
  isSaving?: boolean;
  onSave: (values: {
    name: string;
    description?: string;
    folder?: string;
    visibility: WorkflowVisibility;
  }) => void;
  onClose: () => void;
}

export function WorkflowSaveAsDialog({
  open,
  defaultName = "",
  defaultDescription = "",
  defaultFolder = "/",
  defaultVisibility = "private",
  isSaving = false,
  onSave,
  onClose,
}: WorkflowSaveAsDialogProps) {
  const [nameConflictError, setNameConflictError] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState(false);

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
    },
  });

  const visibility = useWatch({ control, name: "visibility" });

  const onSubmit = useCallback(
    async (values: SaveAsFormValues) => {
      setNameConflictError(null);
      setIsChecking(true);
      try {
        const folder = values.folder || "/";
        const params = new URLSearchParams({
          name: values.name,
          folder,
          visibility: values.visibility,
        });
        const res = await fetch(`/api/proxy/workflows/check-name?${params.toString()}`, {
          credentials: "include",
        });
        if (res.ok) {
          const check = await res.json() as { available: boolean; message?: string };
          if (!check.available) {
            setNameConflictError(check.message ?? "A workflow with this name already exists.");
            return;
          }
        }
      } catch {
        // Ignore check errors and let the save attempt handle it
      } finally {
        setIsChecking(false);
      }
      onSave(values);
    },
    [onSave],
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
                onChange: () => setNameConflictError(null),
              })}
            />
            {errors.name ? (
              <p className="text-xs text-destructive">{errors.name.message}</p>
            ) : null}
            {nameConflictError ? (
              <p className="text-xs text-destructive">{nameConflictError}</p>
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
                onChange: () => setNameConflictError(null),
              })}
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="wf-visibility">Visibility</Label>
            <Select
              value={visibility}
              onValueChange={(v) => {
                setValue("visibility", v as WorkflowVisibility);
                setNameConflictError(null);
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
