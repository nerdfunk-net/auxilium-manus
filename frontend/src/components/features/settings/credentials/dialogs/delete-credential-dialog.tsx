"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface DeleteCredentialDialogProps {
  open: boolean;
  credentialName?: string;
  isDeleting?: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function DeleteCredentialDialog({
  open,
  credentialName,
  isDeleting = false,
  onClose,
  onConfirm,
}: DeleteCredentialDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Delete SSH login?</DialogTitle>
          <DialogDescription>
            This permanently removes{" "}
            <span className="font-mono">{credentialName ?? "this credential"}</span>
            . Workflow steps referencing it will need a new credential.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={isDeleting}
            onClick={onConfirm}
          >
            {isDeleting ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
