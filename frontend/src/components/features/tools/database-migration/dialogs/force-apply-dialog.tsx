"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ColumnDiff } from "@/hooks/queries/use-schema-query";

import { DiffTable } from "../components/schema-diff-tables";

interface ForceApplyDialogProps {
  open: boolean;
  diffs: ColumnDiff[];
  isApplying: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function ForceApplyDialog({
  open,
  diffs,
  isApplying,
  onClose,
  onConfirm,
}: ForceApplyDialogProps) {
  const [acknowledged, setAcknowledged] = useState(false);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setAcknowledged(false);
          onClose();
        }
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Apply risky column changes?</DialogTitle>
          <DialogDescription>
            These changes may truncate or reject existing data. Review them carefully before
            proceeding.
          </DialogDescription>
        </DialogHeader>

        <DiffTable diffs={diffs} />

        <label className="flex cursor-pointer items-start gap-2 text-sm">
          <Checkbox
            checked={acknowledged}
            onCheckedChange={(checked) => setAcknowledged(checked === true)}
            className="mt-0.5"
          />
          I understand this may cause irreversible data loss.
        </label>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={!acknowledged || isApplying}
            onClick={onConfirm}
          >
            {isApplying ? "Applying…" : "Apply Risky Changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
