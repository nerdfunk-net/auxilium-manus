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
import { Textarea } from "@/components/ui/textarea";
import {
  SharedSecretSourceField,
  type SharedSecretSourceMode,
} from "@/components/features/workflow-steps/shared/shared-secret-source-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDecryptAttributeTestMutation } from "@/hooks/queries/use-crypto-attribute-mutations";
import {
  DECRYPT_STEP_ALGORITHMS,
  DEFAULT_SHARED_SECRET_ALGORITHM,
  isKeylessAlgorithm,
} from "@/lib/shared-secret-algorithms";

interface DecryptAttributeTestDialogProps {
  onClose: () => void;
  /** The step's algorithm override; blank means "trust the token header" (AES-GCM). */
  algorithm: string;
}

/** Mounted only while open (parent gates with `{testOpen && ...}`), so state
 * initializers reset the form on every open without an effect. */
export function DecryptAttributeTestDialog({
  onClose,
  algorithm,
}: DecryptAttributeTestDialogProps) {
  const [ciphertext, setCiphertext] = useState("");
  const [secretMode, setSecretMode] = useState<SharedSecretSourceMode>("credential");
  const [credentialReference, setCredentialReference] = useState("");
  const [manualSecret, setManualSecret] = useState("");
  const [algo, setAlgo] = useState(algorithm || DEFAULT_SHARED_SECRET_ALGORITHM);
  const mutation = useDecryptAttributeTestMutation();

  const keyless = isKeylessAlgorithm(algo);
  const hasSecret =
    keyless ||
    (secretMode === "credential" ? credentialReference.length > 0 : manualSecret.length > 0);
  const canSubmit = ciphertext.trim().length > 0 && hasSecret && !mutation.isPending;

  const handleSubmit = () => {
    if (!canSubmit) {
      return;
    }
    if (keyless) {
      mutation.mutate({ ciphertext: ciphertext.trim(), algorithm: algo });
      return;
    }
    mutation.mutate(
      secretMode === "credential"
        ? { ciphertext: ciphertext.trim(), credential_reference: credentialReference }
        : { ciphertext: ciphertext.trim(), shared_secret: manualSecret },
    );
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
            <Textarea
              id="dec-test-ciphertext"
              className="h-20 resize-none rounded-lg bg-card px-2 py-1.5 font-mono text-[11px]"
              value={ciphertext}
              onChange={(event) => setCiphertext(event.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-[11px] text-muted-foreground">Algorithm</Label>
            <Select value={algo} onValueChange={setAlgo}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DECRYPT_STEP_ALGORITHMS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {keyless ? null : (
            <SharedSecretSourceField
              idPrefix="dec-test"
              mode={secretMode}
              onModeChange={setSecretMode}
              credentialReference={credentialReference}
              onCredentialReferenceChange={setCredentialReference}
              manualSecret={manualSecret}
              onManualSecretChange={setManualSecret}
            />
          )}

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
