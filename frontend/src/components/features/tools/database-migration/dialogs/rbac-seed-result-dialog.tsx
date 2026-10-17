"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { RbacSeedResult } from "@/hooks/queries/use-rbac-seed-mutation";

interface RbacSeedResultDialogProps {
  open: boolean;
  result: RbacSeedResult | null;
  onClose: () => void;
}

export function RbacSeedResultDialog({ open, result, onClose }: RbacSeedResultDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{result?.success ? "RBAC seed complete" : "RBAC seed failed"}</DialogTitle>
        </DialogHeader>
        {result && (
          <div className="space-y-2 text-sm">
            <p>{result.message}</p>
            <p className="text-muted-foreground">
              {result.permissions_seeded} permission(s), {result.roles_seeded} role(s)
              {result.removed_existing ? " (existing data was removed first)" : ""}.
            </p>
          </div>
        )}
        <DialogFooter>
          <Button type="button" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
