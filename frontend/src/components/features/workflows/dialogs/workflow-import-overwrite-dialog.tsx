"use client";

import { Button } from "@/components/ui/button";

interface PendingOverwrite {
  message: string;
  existingId: number;
}

interface WorkflowImportOverwriteDialogProps {
  pendingOverwrite: PendingOverwrite | null;
  onConfirm: () => void;
  onCancel: () => void;
}

export function WorkflowImportOverwriteDialog({
  pendingOverwrite,
  onConfirm,
  onCancel,
}: WorkflowImportOverwriteDialogProps) {
  if (!pendingOverwrite) return null;

  return (
    <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs">
      <p className="text-destructive">{pendingOverwrite.message}</p>
      <div className="mt-2 flex gap-2">
        <Button
          type="button"
          size="sm"
          variant="destructive"
          onClick={onConfirm}
        >
          Overwrite
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onCancel}>
          Choose different name
        </Button>
      </div>
    </div>
  );
}
