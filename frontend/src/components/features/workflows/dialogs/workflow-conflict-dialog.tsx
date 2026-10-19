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

interface WorkflowConflictDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReload: () => void;
  onSaveAsNew: () => void;
  onOverwrite: () => void;
}

/**
 * Shown when a save is refused with 409: the workflow was changed (another tab, an AI session,
 * an administrator) after this editor loaded it.
 */
export function WorkflowConflictDialog({
  open,
  onOpenChange,
  onReload,
  onSaveAsNew,
  onOverwrite,
}: WorkflowConflictDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>This workflow changed</DialogTitle>
          <DialogDescription>
            Someone else (or an AI session) saved a newer version after you opened it. Reload to
            discard your edits and see the new version, save your canvas as a new workflow, or
            overwrite the newer version with yours.
          </DialogDescription>
        </DialogHeader>
        {/* The actions wrap: a non-wrapping row is wider than the card and pushes buttons out of it. */}
        <DialogFooter className="gap-2 sm:flex-wrap sm:justify-between">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Keep editing
          </Button>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <Button variant="outline" onClick={onSaveAsNew}>
              Save as new workflow
            </Button>
            <Button variant="outline" onClick={onReload}>
              Reload (discard my edits)
            </Button>
            <Button variant="destructive" onClick={onOverwrite}>
              Overwrite
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
