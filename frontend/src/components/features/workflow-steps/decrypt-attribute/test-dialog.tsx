"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useDecryptAttributeTestMutation } from "@/hooks/queries/use-crypto-attribute-mutations";

interface DecryptAttributeTestDialogProps {
  onClose: () => void;
}

/** Mounted only while open (parent gates with `{testOpen && ...}`), so state
 * initializers reset the form on every open without an effect. */
export function DecryptAttributeTestDialog({ onClose }: DecryptAttributeTestDialogProps) {
  const [ciphertext, setCiphertext] = useState("");
  const [sharedSecret, setSharedSecret] = useState("");
  const mutation = useDecryptAttributeTestMutation();

  const canSubmit =
    ciphertext.trim().length > 0 && sharedSecret.length > 0 && !mutation.isPending;

  const handleSubmit = () => {
    if (!canSubmit) {
      return;
    }
    mutation.mutate({ ciphertext: ciphertext.trim(), shared_secret: sharedSecret });
  };

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader className="sr-only">
          <DialogTitle>Test Decryption</DialogTitle>
          <DialogDescription>
            Decrypt a ciphertext token with a shared secret to reveal the value.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <p className="text-sm font-semibold">Test Decryption</p>

          <div className="space-y-1.5">
            <Label className="text-[11px] text-muted-foreground" htmlFor="dec-test-ciphertext">
              Encrypted value (token)
            </Label>
            <textarea
              id="dec-test-ciphertext"
              className="h-20 w-full resize-none rounded-lg border border-input bg-card px-2 py-1.5 font-mono text-[11px] focus:outline-none focus:ring-2 focus:ring-step/40"
              value={ciphertext}
              onChange={(event) => setCiphertext(event.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-[11px] text-muted-foreground" htmlFor="dec-test-secret">
              Shared secret
            </Label>
            <Input
              id="dec-test-secret"
              type="password"
              autoComplete="off"
              className="h-8 font-mono text-xs"
              value={sharedSecret}
              onChange={(event) => setSharedSecret(event.target.value)}
            />
          </div>

          {mutation.isError ? (
            <p className="text-[11px] text-destructive">{mutation.error.message}</p>
          ) : null}

          {mutation.data ? (
            <div className="space-y-1.5">
              <Label className="text-[11px] text-muted-foreground">
                Decrypted value ({mutation.data.algorithm})
              </Label>
              <Input
                readOnly
                className="h-8 font-mono text-xs"
                value={mutation.data.plaintext}
                onFocus={(event) => event.target.select()}
              />
            </div>
          ) : null}
        </div>

        <DialogFooter className="border-t bg-card px-4 py-3">
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button type="button" disabled={!canSubmit} onClick={handleSubmit}>
            {mutation.isPending ? "Decrypting…" : "Decrypt"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
