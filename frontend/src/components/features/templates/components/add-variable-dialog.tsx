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

interface AddVariableDialogProps {
  open: boolean;
  existingNames: string[];
  onClose: () => void;
  onAdd: (name: string, value: string) => void;
}

export function AddVariableDialog({
  open,
  existingNames,
  onClose,
  onAdd,
}: AddVariableDialogProps) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setName("");
    setValue("");
    setError(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleAdd = () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Variable name is required");
      return;
    }
    if (existingNames.includes(trimmed)) {
      setError("A variable with this name already exists");
      return;
    }
    onAdd(trimmed, value);
    reset();
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && handleClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add Variable</DialogTitle>
          <DialogDescription>
            Add a custom variable available to your template. Values can be plain text
            or JSON.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="variable-name">Name</Label>
            <Input
              id="variable-name"
              placeholder="e.g. hostname"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setError(null);
              }}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="variable-value">Value</Label>
            <Textarea
              id="variable-value"
              placeholder='e.g. "router-1" or {"key": "value"}'
              rows={4}
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
          </div>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button type="button" onClick={handleAdd}>
            Add Variable
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
