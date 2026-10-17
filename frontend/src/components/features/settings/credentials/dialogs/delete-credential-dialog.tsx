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

import type { CredentialDependant } from "../types";
import { describeDependantKind } from "../utils/credential-dependants";

interface DeleteCredentialDialogProps {
  open: boolean;
  credentialName?: string;
  /** Set after the server refused the delete because these still use the credential. */
  dependants?: CredentialDependant[] | null;
  isDeleting?: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function DeleteCredentialDialog({
  open,
  credentialName,
  dependants = null,
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
        {dependants !== null && (
          <div className="space-y-2 text-sm" role="alert">
            <p className="font-medium text-destructive">
              Still in use by {dependants.length}{" "}
              {dependants.length === 1 ? "item" : "items"}. Deleting it breaks them.
            </p>
            <ul className="max-h-48 space-y-1 overflow-y-auto rounded-md border bg-muted p-2">
              {dependants.map((item) => (
                <li key={`${item.kind}-${item.id}`} className="flex gap-2">
                  <span className="text-muted-foreground">
                    {describeDependantKind(item.kind)}
                  </span>
                  <span className="font-mono">{item.name}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
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
            {isDeleting
              ? "Deleting…"
              : dependants !== null
                ? "Delete anyway"
                : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
