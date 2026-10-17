"use client";

import type {
  FieldErrors,
  UseFormRegister,
  UseFormSetValue,
} from "react-hook-form";

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
import { WorkflowImportOverwriteDialog } from "./workflow-import-overwrite-dialog";

interface ImportFormValues {
  name: string;
  description?: string;
  folder?: string;
  visibility: WorkflowVisibility;
}

interface PendingOverwrite {
  message: string;
  existingId: number;
}

interface WorkflowImportMetadataFieldsProps {
  importFile: unknown;
  register: UseFormRegister<ImportFormValues>;
  errors: FieldErrors<ImportFormValues>;
  visibility: WorkflowVisibility;
  setValue: UseFormSetValue<ImportFormValues>;
  onClearPendingOverwrite: () => void;
  pendingOverwrite: PendingOverwrite | null;
  onConfirmOverwrite: () => void;
  showTemplateSummary: boolean;
  templateImportSummary: { reuse: string[]; create: string[] };
}

export function WorkflowImportMetadataFields({
  importFile,
  register,
  errors,
  visibility,
  setValue,
  onClearPendingOverwrite,
  pendingOverwrite,
  onConfirmOverwrite,
  showTemplateSummary,
  templateImportSummary,
}: WorkflowImportMetadataFieldsProps) {
  return (
    <>
      <div className="grid gap-1.5">
        <Label htmlFor="import-name">Name</Label>
        <Input
          id="import-name"
          placeholder="My workflow"
          disabled={!importFile}
          {...register("name", { onChange: onClearPendingOverwrite })}
        />
        {errors.name ? (
          <p className="text-xs text-destructive">{errors.name.message}</p>
        ) : null}
        <WorkflowImportOverwriteDialog
          pendingOverwrite={pendingOverwrite}
          onConfirm={onConfirmOverwrite}
          onCancel={onClearPendingOverwrite}
        />
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
          {...register("folder", { onChange: onClearPendingOverwrite })}
        />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="import-visibility">Visibility</Label>
        <Select
          value={visibility}
          onValueChange={(v) => {
            setValue("visibility", v as WorkflowVisibility);
            onClearPendingOverwrite();
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
    </>
  );
}
