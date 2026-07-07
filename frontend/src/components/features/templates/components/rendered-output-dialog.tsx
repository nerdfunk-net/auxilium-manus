"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { TemplateRenderResponse } from "../types";

interface RenderedOutputDialogProps {
  open: boolean;
  result: TemplateRenderResponse | null;
  onOpenChange: (open: boolean) => void;
}

export function RenderedOutputDialog({
  open,
  result,
  onOpenChange,
}: RenderedOutputDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] max-w-3xl overflow-hidden">
        <DialogHeader>
          <DialogTitle>Rendered Template</DialogTitle>
          <DialogDescription>
            {result?.variables_used.length
              ? `Variables used: ${result.variables_used.join(", ")}`
              : "Preview of the rendered output"}
          </DialogDescription>
        </DialogHeader>
        {result?.warnings.length ? (
          <ul className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
            {result.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : null}
        <div className="max-h-[60vh] overflow-auto rounded-md border bg-muted/30 p-4">
          <pre className="whitespace-pre-wrap break-words font-mono text-xs text-foreground">
            {result?.rendered_content || "(empty output)"}
          </pre>
        </div>
      </DialogContent>
    </Dialog>
  );
}
