"use client";

import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

import type { WorkflowExportFile } from "../types/workflow-export";
import { parseWorkflowExportFile } from "../utils/workflow-import";

interface WorkflowImportFileFieldProps {
  importFile: WorkflowExportFile | null;
  parseError: string | null;
  onParsed: (file: WorkflowExportFile) => void;
  onError: (message: string) => void;
}

export function WorkflowImportFileField({
  importFile,
  parseError,
  onParsed,
  onError,
}: WorkflowImportFileFieldProps) {
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
        onParsed(parsed);
      } catch (err) {
        onError(
          err instanceof Error
            ? err.message
            : "Could not read the selected file.",
        );
      }
    };
    input.click();
  }, [onParsed, onError]);

  return (
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
  );
}
