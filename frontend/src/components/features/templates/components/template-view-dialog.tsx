"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { useTemplateQuery } from "../hooks/use-template-query";

interface TemplateViewDialogProps {
  templateId: number | null;
  templateName?: string;
  open: boolean;
  onClose: () => void;
}

export function TemplateViewDialog({
  templateId,
  templateName,
  open,
  onClose,
}: TemplateViewDialogProps) {
  const { data, isLoading, error } = useTemplateQuery({
    templateId,
    enabled: open,
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[80vh] max-w-3xl overflow-hidden">
        <DialogHeader>
          <DialogTitle>{templateName ?? "Template"}</DialogTitle>
          <DialogDescription>Read-only template content</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-auto rounded-md border bg-muted/30 p-4">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : error ? (
            <p className="text-sm text-destructive">{error.message}</p>
          ) : (
            <pre className="whitespace-pre-wrap break-words font-mono text-xs text-foreground">
              {data?.content || "(empty template)"}
            </pre>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
