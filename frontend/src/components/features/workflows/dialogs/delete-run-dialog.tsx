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

interface DeleteRunDialogProps {
  open: boolean;
  runIds: number[];
  isDeleting?: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function DeleteRunDialog({
  open,
  runIds,
  isDeleting = false,
  onClose,
  onConfirm,
}: DeleteRunDialogProps) {
  const isBulk = runIds.length > 1;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{isBulk ? `Delete ${runIds.length} runs?` : `Delete run #${runIds[0]}?`}</DialogTitle>
          <DialogDescription>
            {isBulk
              ? `This permanently removes ${runIds.length} runs and all of their step results and logs.`
              : "This permanently removes the run and all of its step results and logs."}
            {" "}This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={isDeleting || runIds.length === 0}
            onClick={onConfirm}
          >
            {isDeleting ? "Deleting…" : isBulk ? `Delete ${runIds.length} runs` : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
