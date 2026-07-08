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

import { NAUTOBOT_ATTRIBUTE_GROUPS } from "../constants";

interface AttributesDialogProps {
  open: boolean;
  value: string[];
  onOpenChange: (open: boolean) => void;
  onChange: (selected: string[]) => void;
}

export function AttributesDialog({
  open,
  value,
  onOpenChange,
  onChange,
}: AttributesDialogProps) {
  const [selected, setSelected] = useState<string[]>(value);

  const handleToggle = useCallback((key: string) => {
    setSelected((prev) =>
      prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key],
    );
  }, []);

  const handleSave = useCallback(() => {
    onChange(selected);
    onOpenChange(false);
  }, [selected, onChange, onOpenChange]);

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (isOpen) {
          setSelected(value);
        } else {
          onOpenChange(false);
        }
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Nautobot attributes</DialogTitle>
          <DialogDescription>
            Choose which Nautobot attribute groups to fetch into the{" "}
            <code>nautobot</code> variable. Base fields (role, platform,
            location, status, primary_ip4) are always included. These match the
            &quot;Get Nautobot Attributes&quot; workflow step.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          {NAUTOBOT_ATTRIBUTE_GROUPS.map(({ key, label }) => (
            <label
              key={key}
              className="flex cursor-pointer items-center gap-3 rounded-lg px-1 py-0.5 hover:bg-muted/50"
            >
              <input
                type="checkbox"
                className="size-4 rounded border"
                checked={selected.includes(key)}
                onChange={() => handleToggle(key)}
              />
              <span className="text-sm">{label}</span>
              <span className="ml-auto font-mono text-[11px] text-muted-foreground">
                nautobot.{key === "secret_groups" ? "secrets_group" : key}
              </span>
            </label>
          ))}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            size="sm"
            type="button"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button size="sm" type="button" onClick={handleSave}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
