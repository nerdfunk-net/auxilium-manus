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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  SharedSecretSourceField,
  type SharedSecretSourceMode,
} from "@/components/features/workflow-steps/shared/shared-secret-source-field";
import { useEncryptAttributeTestMutation } from "@/hooks/queries/use-crypto-attribute-mutations";
import {
  DEFAULT_SHARED_SECRET_ALGORITHM,
  SHARED_SECRET_ALGORITHMS,
} from "@/lib/shared-secret-algorithms";

interface EncryptAttributeTestDialogProps {
  onClose: () => void;
  /** Blank means "use the credential default"; the modal picks a concrete algorithm. */
  algorithm: string;
}

/** Mounted only while open (parent gates with `{testOpen && ...}`), so state
 * initializers reset the form on every open without an effect. */
export function EncryptAttributeTestDialog({
  onClose,
  algorithm,
}: EncryptAttributeTestDialogProps) {
  const [plaintext, setPlaintext] = useState("");
  const [secretMode, setSecretMode] = useState<SharedSecretSourceMode>("credential");
  const [credentialReference, setCredentialReference] = useState("");
  const [manualSecret, setManualSecret] = useState("");
  const [algo, setAlgo] = useState(algorithm || DEFAULT_SHARED_SECRET_ALGORITHM);
  const mutation = useEncryptAttributeTestMutation();

  const hasSecret =
    secretMode === "credential" ? credentialReference.length > 0 : manualSecret.length > 0;
  const canSubmit = plaintext.length > 0 && hasSecret && !mutation.isPending;

  const handleSubmit = () => {
    if (!canSubmit) {
      return;
    }
    mutation.mutate(
      secretMode === "credential"
        ? { plaintext, credential_reference: credentialReference, algorithm: algo }
        : { plaintext, shared_secret: manualSecret, algorithm: algo },
    );
  };

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader className="sr-only">
          <DialogTitle>Test Encryption</DialogTitle>
          <DialogDescription>
            Encrypt a sample value with a shared secret to verify the result.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <p className="text-sm font-semibold">Test Encryption</p>

          <div className="space-y-1.5">
            <Label className="text-[11px] text-muted-foreground" htmlFor="enc-test-plaintext">
              Cleartext value
            </Label>
            <Input
              id="enc-test-plaintext"
              className="h-8 font-mono text-xs"
              value={plaintext}
              onChange={(event) => setPlaintext(event.target.value)}
            />
          </div>

          <SharedSecretSourceField
            idPrefix="enc-test"
            mode={secretMode}
            onModeChange={setSecretMode}
            credentialReference={credentialReference}
            onCredentialReferenceChange={setCredentialReference}
            manualSecret={manualSecret}
            onManualSecretChange={setManualSecret}
          />

          <div className="space-y-1.5">
            <Label className="text-[11px] text-muted-foreground">Algorithm</Label>
            <Select value={algo} onValueChange={setAlgo}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SHARED_SECRET_ALGORITHMS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {mutation.isError ? (
            <p className="text-[11px] text-destructive">{mutation.error.message}</p>
          ) : null}

          {mutation.data ? (
            <div className="space-y-1.5">
              <Label className="text-[11px] text-muted-foreground">Ciphertext token</Label>
              <textarea
                readOnly
                className="h-24 w-full resize-none rounded-lg border border-input bg-muted/50 px-2 py-1.5 font-mono text-[11px]"
                value={mutation.data.ciphertext}
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
            {mutation.isPending ? "Encrypting…" : "Encrypt"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
