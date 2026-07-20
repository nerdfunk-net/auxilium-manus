"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
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
  createAttributeUpdate,
  type AttributeUpdate,
  type RegexFlags,
  type UpdateAttributeMode,
} from "./update-attribute-config";

function AttributePathHelp() {
  return (
    <p className="text-[11px] leading-4 text-muted-foreground">
      Use <span className="font-mono">device.name</span> for core device fields,{" "}
      <span className="font-mono">nautobot.location.name</span> for Nautobot attributes, or{" "}
      <span className="font-mono">custom.field</span> for user-defined attribute bags.
    </p>
  );
}

function RegexFlagsFields({
  flags,
  fieldId,
  onChange,
}: {
  flags: RegexFlags;
  fieldId: string;
  onChange: (patch: Partial<RegexFlags>) => void;
}) {
  const items: Array<{ key: keyof RegexFlags; label: string; description: string }> = [
    {
      key: "case_insensitive",
      label: "case_insensitive",
      description: "Ignore letter case when matching.",
    },
    {
      key: "multiline",
      label: "multiline",
      description: "Treat start/end anchors per line.",
    },
    {
      key: "dotall",
      label: "dotall",
      description: "Let . match newline characters.",
    },
  ];

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">regex_flags</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          object
        </Badge>
      </div>
      <div className="space-y-2 rounded-lg border p-3">
        {items.map((item) => (
          <div key={item.key} className="flex items-start gap-2">
            <input
              id={`${item.key}-${fieldId}`}
              type="checkbox"
              checked={flags[item.key]}
              onChange={(event) => onChange({ [item.key]: event.target.checked })}
              className="mt-0.5 size-4 rounded border accent-teal-500"
            />
            <div className="space-y-0.5">
              <Label htmlFor={`${item.key}-${fieldId}`} className="font-mono text-xs font-medium">
                {item.label}
              </Label>
              <p className="text-[11px] text-muted-foreground">{item.description}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export interface AttributeUpdateEditorProps {
  value: AttributeUpdate;
  onChange: (value: AttributeUpdate) => void;
  fieldId?: string;
}

export function AttributeUpdateEditor({
  value,
  onChange,
  fieldId = "attribute-editor",
}: AttributeUpdateEditorProps) {
  const handleModeChange = useCallback(
    (mode: UpdateAttributeMode) => {
      onChange({ ...value, mode });
    },
    [onChange, value],
  );

  const handleRegexFlagsChange = useCallback(
    (patch: Partial<RegexFlags>) => {
      onChange({
        ...value,
        regex_flags: {
          ...value.regex_flags,
          ...patch,
        },
      });
    },
    [onChange, value],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">mode</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select
          value={value.mode}
          onValueChange={(next) => handleModeChange(next as UpdateAttributeMode)}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Select mode" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="fixed">Fixed value</SelectItem>
            <SelectItem value="regex">Regular expression</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Fixed value writes a literal to the destination path. Regular expression reads a
          source attribute, matches a pattern, and writes an expanded destination value.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">destination_path</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={value.destination_path}
          onChange={(event) =>
            onChange({ ...value, destination_path: event.target.value })
          }
          placeholder="custom.location"
          className="h-8 font-mono text-xs"
        />
        <AttributePathHelp />
      </div>

      {value.mode === "fixed" ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">fixed_value</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Input
            value={value.fixed_value}
            onChange={(event) => onChange({ ...value, fixed_value: event.target.value })}
            placeholder="office-a"
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] leading-4 text-muted-foreground">
            The value is written to the destination path, creating or overwriting the attribute
            in the workflow context.
          </p>
        </div>
      ) : (
        <>
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">source_path</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={value.source_path}
              onChange={(event) => onChange({ ...value, source_path: event.target.value })}
              placeholder="device.name"
              className="h-8 font-mono text-xs"
            />
            <AttributePathHelp />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">pattern</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={value.pattern}
              onChange={(event) => onChange({ ...value, pattern: event.target.value })}
              placeholder={String.raw`^([^-]+)-`}
              className="h-8 font-mono text-xs"
            />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">destination_template</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={value.destination_template}
              onChange={(event) =>
                onChange({ ...value, destination_template: event.target.value })
              }
              placeholder={String.raw`DC-\1`}
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] leading-4 text-muted-foreground">
              Use Python backrefs such as <span className="font-mono">{"\\1"}</span> or{" "}
              <span className="font-mono">{"\\g<location>"}</span> with named groups.
            </p>
          </div>

          <RegexFlagsFields
            flags={value.regex_flags}
            fieldId={fieldId}
            onChange={handleRegexFlagsChange}
          />
        </>
      )}
    </div>
  );
}

function validateAttributeDraft(draft: AttributeUpdate): string | null {
  if (!draft.destination_path.trim()) {
    return "destination_path is required.";
  }
  if (draft.mode === "fixed") {
    if (!draft.fixed_value.trim()) {
      return "fixed_value is required in fixed mode.";
    }
    return null;
  }
  if (!draft.source_path.trim()) {
    return "source_path is required in regex mode.";
  }
  if (!draft.pattern.trim()) {
    return "pattern is required in regex mode.";
  }
  if (!draft.destination_template.trim()) {
    return "destination_template is required in regex mode.";
  }
  return null;
}

interface AttributeUpdateDialogProps {
  open: boolean;
  mode: "add" | "edit";
  initialValue: AttributeUpdate | null;
  onClose: () => void;
  onSave: (value: AttributeUpdate) => void;
}

export function AttributeUpdateDialog({
  open,
  mode,
  initialValue,
  onClose,
  onSave,
}: AttributeUpdateDialogProps) {
  const [draft, setDraft] = useState<AttributeUpdate>(() => createAttributeUpdate());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setDraft(initialValue ?? createAttributeUpdate());
    setError(null);
  }, [open, initialValue]);

  const handleOpenChange = useCallback(
    (isOpen: boolean) => {
      if (!isOpen) {
        setError(null);
        onClose();
      }
    },
    [onClose],
  );

  const handleSave = useCallback(() => {
    const validationError = validateAttributeDraft(draft);
    if (validationError) {
      setError(validationError);
      return;
    }
    onSave({
      ...draft,
      destination_path: draft.destination_path.trim(),
      source_path: draft.source_path.trim(),
      pattern: draft.pattern,
      destination_template: draft.destination_template,
      fixed_value: draft.fixed_value,
    });
    setError(null);
  }, [draft, onSave]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-lg">
        <DialogHeader className="shrink-0 border-b bg-gradient-to-r from-teal-600 to-teal-500 px-4 py-3 text-white">
          <DialogTitle className="text-base text-white">
            {mode === "add" ? "Add attribute update" : "Edit attribute update"}
          </DialogTitle>
          <DialogDescription className="sr-only">
            Configure mode, destination path, and value or regex transform for this attribute
            update.
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-y-auto bg-slate-50 p-4">
          <AttributeUpdateEditor
            value={draft}
            onChange={(next) => {
              setDraft(next);
              setError(null);
            }}
            fieldId="attribute-dialog"
          />
          {error ? (
            <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {error}
            </p>
          ) : null}
        </div>

        <DialogFooter className="shrink-0 border-t bg-white px-4 py-3">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            size="sm"
            className="bg-teal-500 text-white hover:bg-teal-600"
            onClick={handleSave}
          >
            {mode === "add" ? "Add" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
