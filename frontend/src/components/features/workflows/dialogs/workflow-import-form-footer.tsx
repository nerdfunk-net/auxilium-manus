"use client";

import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";

interface WorkflowImportFormFooterProps {
  onClose: () => void;
  disabled: boolean;
  submitLabel: string;
}

export function WorkflowImportFormFooter({
  onClose,
  disabled,
  submitLabel,
}: WorkflowImportFormFooterProps) {
  return (
    <DialogFooter>
      <Button type="button" variant="outline" onClick={onClose}>
        Cancel
      </Button>
      <Button type="submit" disabled={disabled}>
        {submitLabel}
      </Button>
    </DialogFooter>
  );
}
