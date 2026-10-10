"use client";

import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";

interface ShareConfirmSwitchProps {
  checked: boolean;
  disabled?: boolean;
  /** Setting name shown in the dialog title. */
  label: string;
  /** What will be sent to the model, and the residual risk. */
  warning: string;
  onChange: (checked: boolean) => void;
}

/**
 * A data-sharing switch. Turning it off is immediate; turning it on asks for confirmation first,
 * because the data then leaves the app for the selected provider (redaction is best-effort).
 */
export function ShareConfirmSwitch({
  checked,
  disabled = false,
  label,
  warning,
  onChange,
}: ShareConfirmSwitchProps) {
  const [confirming, setConfirming] = useState(false);

  const handleToggle = useCallback(
    (next: boolean) => {
      if (next) {
        setConfirming(true);
      } else {
        onChange(false);
      }
    },
    [onChange],
  );
  const handleConfirm = useCallback(() => {
    setConfirming(false);
    onChange(true);
  }, [onChange]);

  return (
    <>
      <Switch
        checked={checked}
        disabled={disabled}
        onCheckedChange={handleToggle}
        aria-label={label}
      />
      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Share “{label}” with the model?</DialogTitle>
            <DialogDescription>{warning}</DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Automatic redaction of passwords and keys is best-effort, not a
            guarantee. You can switch this off again at any time; it applies
            from the next message.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button onClick={handleConfirm}>Share</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
