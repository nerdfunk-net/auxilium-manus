"use client";

import { useCallback, useState } from "react";
import { useForm } from "react-hook-form";
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

import { useTemplateMutations } from "../hooks/use-template-mutations";
import { useTemplatesQuery } from "../hooks/use-templates-query";
import type { TemplateExportFile } from "../types/template-export";
import { templateExportToCreatePayload } from "../utils/template-export";
import { parseTemplateExportFile } from "../utils/template-import";

const importSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
});

type ImportFormValues = z.infer<typeof importSchema>;

interface TemplateImportDialogProps {
  open: boolean;
  onClose: () => void;
}

export function TemplateImportDialog({
  open,
  onClose,
}: TemplateImportDialogProps) {
  const { createTemplate, updateTemplate } = useTemplateMutations();
  const { data: templatesData } = useTemplatesQuery({ enabled: open });

  const [importFile, setImportFile] = useState<TemplateExportFile | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [pendingOverwrite, setPendingOverwrite] = useState<{
    existingId: number;
    values: ImportFormValues;
  } | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ImportFormValues>({
    resolver: zodResolver(importSchema),
    defaultValues: { name: "" },
  });

  const isSaving = createTemplate.isPending || updateTemplate.isPending;

  const resetState = useCallback(() => {
    setImportFile(null);
    setParseError(null);
    setPendingOverwrite(null);
    reset({ name: "" });
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
        const parsed = parseTemplateExportFile(JSON.parse(text));
        setImportFile(parsed);
        setParseError(null);
        setPendingOverwrite(null);
        reset({ name: parsed.name });
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
    async (values: ImportFormValues, overwriteId?: number) => {
      if (!importFile) return;

      const payload = templateExportToCreatePayload({
        ...importFile,
        name: values.name,
      });

      try {
        if (overwriteId !== undefined) {
          await updateTemplate.mutateAsync({
            templateId: overwriteId,
            payload,
          });
        } else {
          await createTemplate.mutateAsync(payload);
        }
        handleClose();
      } catch {
        // Error toast handled by mutation
      }
    },
    [importFile, createTemplate, updateTemplate, handleClose],
  );

  const onSubmit = useCallback(
    (values: ImportFormValues) => {
      if (!importFile) return;
      setPendingOverwrite(null);

      const existing = (templatesData?.templates ?? []).find(
        (template) => template.name === values.name,
      );
      if (existing) {
        setPendingOverwrite({ existingId: existing.id, values });
        return;
      }
      void performSave(values);
    },
    [importFile, templatesData?.templates, performSave],
  );

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Import Template</DialogTitle>
          <DialogDescription>
            Import a template from a previously exported JSON file.
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
            <Label htmlFor="template-import-name">Name</Label>
            <Input
              id="template-import-name"
              placeholder="My template"
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
                <p className="text-destructive">
                  A template named &quot;{pendingOverwrite.values.name}&quot;
                  already exists.
                </p>
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

          {importFile ? (
            <p className="text-xs text-muted-foreground">
              Type: {importFile.template_type} · Category: {importFile.category}
            </p>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!importFile || isSaving}>
              {isSaving ? "Importing…" : "Import"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
