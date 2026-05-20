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

import { ATTRIBUTE_GROUPS, type AttributeGroupKey } from "./types";

interface AttributesDialogProps {
  open: boolean;
  onClose: () => void;
  value: AttributeGroupKey[];
  onChange: (selected: AttributeGroupKey[]) => void;
}

export function AttributesDialog({
  open,
  onClose,
  value,
  onChange,
}: AttributesDialogProps) {
  const [selected, setSelected] = useState<AttributeGroupKey[]>(value);

  const handleOpen = useCallback(() => {
    setSelected(value);
  }, [value]);

  const handleToggle = useCallback((key: AttributeGroupKey) => {
    setSelected((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  }, []);

  const handleSave = useCallback(() => {
    onChange(selected);
    onClose();
  }, [selected, onChange, onClose]);

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (isOpen) handleOpen();
        else onClose();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Select Attribute Groups</DialogTitle>
          <DialogDescription>
            Choose which Nautobot attribute groups to retrieve for each device.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          {ATTRIBUTE_GROUPS.map(({ key, label }) => (
            <label
              key={key}
              className="flex cursor-pointer items-center gap-3 rounded-lg px-1 py-0.5 hover:bg-muted/50"
            >
              <input
                type="checkbox"
                className="h-4 w-4 rounded accent-teal-500 focus:ring-2 focus:ring-teal-400/40"
                checked={selected.includes(key)}
                onChange={() => handleToggle(key)}
              />
              <span className="text-sm">{label}</span>
            </label>
          ))}
        </div>

        <DialogFooter className="shrink-0 border-t bg-white px-4 py-3">
          <Button variant="outline" size="sm" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button size="sm" onClick={handleSave} type="button">
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
