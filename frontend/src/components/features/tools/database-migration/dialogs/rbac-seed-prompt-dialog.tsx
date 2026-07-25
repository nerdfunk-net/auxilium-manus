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

interface RbacSeedPromptDialogProps {
  open: boolean;
  isSeeding: boolean;
  onSkip: () => void;
  onSeed: () => void;
}

export function RbacSeedPromptDialog({
  open,
  isSeeding,
  onSkip,
  onSeed,
}: RbacSeedPromptDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onSkip()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Schema updated — seed RBAC too?</DialogTitle>
          <DialogDescription>
            New tables or columns may introduce new permissions. Run the RBAC seed now to make
            sure the permission catalog is up to date.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onSkip}>
            Skip
          </Button>
          <Button type="button" disabled={isSeeding} onClick={onSeed}>
            {isSeeding ? "Seeding…" : "Seed RBAC"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
