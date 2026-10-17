"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { AddCertificateResult } from "@/hooks/queries/use-certificates-mutations";

interface AddToSystemResultDialogProps {
  open: boolean;
  results: AddCertificateResult[];
  onClose: () => void;
}

export function AddToSystemResultDialog({ open, results, onClose }: AddToSystemResultDialogProps) {
  const allSucceeded = results.length > 0 && results.every((r) => r.success);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {allSucceeded ? "Certificates added successfully" : "Certificate operation results"}
          </DialogTitle>
        </DialogHeader>
        <pre className="max-h-80 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
          {results
            .map((r) =>
              [
                `=== ${r.filename} ===`,
                r.message,
                r.command_output ? r.command_output.trim() : "",
              ]
                .filter(Boolean)
                .join("\n"),
            )
            .join("\n\n")}
        </pre>
        <DialogFooter>
          <Button type="button" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
