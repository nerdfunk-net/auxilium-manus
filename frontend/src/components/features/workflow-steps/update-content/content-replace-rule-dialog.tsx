"use client";

import { useCallback, useState } from "react";

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

import { createReplaceRule, type ContentReplaceRule, type RegexFlags } from "./update-content-config";

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
              className="mt-0.5 size-4 rounded border accent-step"
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

export interface ContentReplaceRuleEditorProps {
  value: ContentReplaceRule;
  onChange: (value: ContentReplaceRule) => void;
  fieldId?: string;
}

export function ContentReplaceRuleEditor({
  value,
  onChange,
  fieldId = "replace-rule-editor",
}: ContentReplaceRuleEditorProps) {
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
          <span className="font-mono text-xs font-medium">pattern</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={value.pattern}
          onChange={(event) => onChange({ ...value, pattern: event.target.value })}
          placeholder={String.raw`ntp server 192\.168\.1\.10`}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Python regular expression matched against the config text.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">replacement</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={value.replacement}
          onChange={(event) => onChange({ ...value, replacement: event.target.value })}
          placeholder="ntp server 192.168.178.10"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Fixed text, or use Python backrefs such as <span className="font-mono">{"\\1"}</span>{" "}
          or <span className="font-mono">{"\\g<name>"}</span> to reuse captured groups.
        </p>
      </div>

      <div className="flex items-start gap-2">
        <input
          id={`replace-all-${fieldId}`}
          type="checkbox"
          checked={value.replace_all}
          onChange={(event) => onChange({ ...value, replace_all: event.target.checked })}
          className="mt-0.5 size-4 rounded border accent-step"
        />
        <div className="space-y-0.5">
          <Label htmlFor={`replace-all-${fieldId}`} className="font-mono text-xs font-medium">
            replace_all
          </Label>
          <p className="text-[11px] text-muted-foreground">
            Replace every match. Uncheck to replace only the first match.
          </p>
        </div>
      </div>

      <RegexFlagsFields
        flags={value.regex_flags}
        fieldId={fieldId}
        onChange={handleRegexFlagsChange}
      />
    </div>
  );
}

function validateRuleDraft(draft: ContentReplaceRule): string | null {
  if (!draft.pattern.trim()) {
    return "pattern is required.";
  }
  return null;
}

interface ContentReplaceRuleDialogProps {
  open: boolean;
  mode: "add" | "edit";
  initialValue: ContentReplaceRule | null;
  onClose: () => void;
  onSave: (value: ContentReplaceRule) => void;
}

function ContentReplaceRuleDialogForm({
  mode,
  initialValue,
  onClose,
  onSave,
}: Omit<ContentReplaceRuleDialogProps, "open">) {
  const [draft, setDraft] = useState<ContentReplaceRule>(
    () => initialValue ?? createReplaceRule(),
  );
  const [error, setError] = useState<string | null>(null);

  const handleSave = useCallback(() => {
    const validationError = validateRuleDraft(draft);
    if (validationError) {
      setError(validationError);
      return;
    }
    onSave(draft);
    setError(null);
  }, [draft, onSave]);

  return (
    <DialogContent className="flex max-h-[85vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-lg">
      <DialogHeader className="shrink-0 border-b step-header px-4 py-3">
        <DialogTitle className="text-base text-step-header-foreground">
          {mode === "add" ? "Add replace rule" : "Edit replace rule"}
        </DialogTitle>
        <DialogDescription className="sr-only">
          Configure the regex pattern, replacement text, and flags for this search/replace
          rule.
        </DialogDescription>
      </DialogHeader>

      <div className="overflow-y-auto bg-muted p-4">
        <ContentReplaceRuleEditor
          value={draft}
          onChange={(next) => {
            setDraft(next);
            setError(null);
          }}
          fieldId="replace-rule-dialog"
        />
        {error ? (
          <p className="mt-3 rounded-lg border border-warning-border bg-warning px-3 py-2 text-xs text-warning-foreground">
            {error}
          </p>
        ) : null}
      </div>

      <DialogFooter className="shrink-0 border-t bg-card px-4 py-3">
        <Button type="button" variant="outline" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="button"
          size="sm"
          className="bg-step text-step-foreground hover:bg-step-hover"
          onClick={handleSave}
        >
          {mode === "add" ? "Add" : "Save"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

export function ContentReplaceRuleDialog({
  open,
  mode,
  initialValue,
  onClose,
  onSave,
}: ContentReplaceRuleDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) {
          onClose();
        }
      }}
    >
      {open ? (
        <ContentReplaceRuleDialogForm
          mode={mode}
          initialValue={initialValue}
          onClose={onClose}
          onSave={onSave}
        />
      ) : null}
    </Dialog>
  );
}
