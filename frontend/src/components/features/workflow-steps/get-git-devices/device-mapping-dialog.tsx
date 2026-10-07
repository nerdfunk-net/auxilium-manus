"use client";

import { Plus, Trash2 } from "lucide-react";
import { useCallback, useId, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

import { NAUTOBOT_TARGETS, targetLabel } from "./constants/nautobot-targets";
import {
  cleanMapping,
  DEFAULT_MAPPING,
  hasMappingErrors,
  validateMapping,
  type DeviceMappingRule,
} from "./utils/device-mapping";

const EMPTY_KEYS: readonly string[] = [];

const TARGET_OPTIONS: ComboboxOption[] = NAUTOBOT_TARGETS.map((target) => ({
  value: target.value,
  label: targetLabel(target.value),
}));

const NEW_ROW: DeviceMappingRule = { source: "", target: "" };

interface DeviceMappingDialogProps {
  open: boolean;
  rules: readonly DeviceMappingRule[];
  /** File keys discovered by the last preview; used as suggestions. */
  availableKeys?: readonly string[];
  loadingKeys: boolean;
  canLoadKeys: boolean;
  onLoadKeys: () => void;
  onClose: () => void;
  onSave: (rules: DeviceMappingRule[]) => void;
}

type EditorProps = Omit<DeviceMappingDialogProps, "open">;

function DeviceMappingEditor({
  rules,
  availableKeys = EMPTY_KEYS,
  loadingKeys,
  canLoadKeys,
  onLoadKeys,
  onClose,
  onSave,
}: EditorProps) {
  const listId = useId();
  const [draft, setDraft] = useState<DeviceMappingRule[]>(() =>
    rules.length > 0 ? [...rules] : [...DEFAULT_MAPPING],
  );
  const [showErrors, setShowErrors] = useState(false);

  const errors = useMemo(() => validateMapping(draft), [draft]);

  const updateRow = useCallback((index: number, patch: Partial<DeviceMappingRule>) => {
    setDraft((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }, []);

  const removeRow = useCallback((index: number) => {
    setDraft((rows) => rows.filter((_, i) => i !== index));
  }, []);

  const addRow = useCallback(() => setDraft((rows) => [...rows, NEW_ROW]), []);
  const resetToDefault = useCallback(() => setDraft([...DEFAULT_MAPPING]), []);

  const handleSave = useCallback(() => {
    if (hasMappingErrors(errors)) {
      setShowErrors(true);
      return;
    }
    onSave(cleanMapping(draft));
  }, [draft, errors, onSave]);

  const usedTargets = useMemo(() => new Set(draft.map((row) => row.target)), [draft]);

  return (
    <>
      <DialogHeader>
        <DialogTitle>Device Mapping</DialogTitle>
        <DialogDescription>
          Map keys of each device entry in the file to Nautobot attributes. Nested keys can be
          written as <code className="font-mono text-xs">parent.child</code>.
        </DialogDescription>
      </DialogHeader>

      <datalist id={listId}>
        {availableKeys.map((key) => (
          <option key={key} value={key} />
        ))}
      </datalist>

      <div className="flex flex-col gap-2">
        <div className="grid grid-cols-[1fr_1fr_auto] gap-2 text-xs font-medium text-muted-foreground">
          <span>File key</span>
          <span>Nautobot attribute</span>
          <span className="w-8" />
        </div>
        {draft.map((row, index) => {
          const rowError = showErrors ? errors.rows[index] : undefined;
          return (
            <div key={index} className="flex flex-col gap-1">
              <div className="grid grid-cols-[1fr_1fr_auto] items-start gap-2">
                <Input
                  aria-label={`File key ${index + 1}`}
                  className="h-8 font-mono text-xs"
                  list={listId}
                  placeholder="device_name"
                  value={row.source}
                  onChange={(e) => updateRow(index, { source: e.target.value })}
                />
                <Combobox
                  className="h-8 text-xs"
                  options={TARGET_OPTIONS.filter(
                    (option) => option.value === row.target || !usedTargets.has(option.value),
                  )}
                  placeholder="Select attribute…"
                  searchPlaceholder="Search attributes…"
                  value={row.target}
                  onValueChange={(target) => updateRow(index, { target })}
                  inline
                />
                <Button
                  aria-label={`Remove mapping ${index + 1}`}
                  className="h-8 w-8"
                  size="icon"
                  type="button"
                  variant="ghost"
                  onClick={() => removeRow(index)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              {rowError && <p className="text-[11px] text-destructive">{rowError}</p>}
            </div>
          );
        })}
        {draft.length === 0 && (
          <p className="text-xs text-muted-foreground">
            No rows. Saving an empty mapping uses the default (name, primary_ip4, network_driver).
          </p>
        )}
        {showErrors && errors.form && <p className="text-[11px] text-destructive">{errors.form}</p>}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button className="h-7 text-xs" size="sm" type="button" variant="outline" onClick={addRow}>
          <Plus className="mr-1 h-3 w-3" />
          Add mapping
        </Button>
        <Button
          className="h-7 text-xs"
          size="sm"
          type="button"
          variant="outline"
          disabled={!canLoadKeys || loadingKeys}
          onClick={onLoadKeys}
        >
          {loadingKeys ? "Loading keys…" : `Load keys from repository (${availableKeys.length})`}
        </Button>
        <Button
          className="h-7 text-xs"
          size="sm"
          type="button"
          variant="ghost"
          onClick={resetToDefault}
        >
          Reset to default
        </Button>
      </div>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="button" onClick={handleSave}>
          Save mapping
        </Button>
      </DialogFooter>
    </>
  );
}

export function DeviceMappingDialog({ open, ...editorProps }: DeviceMappingDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && editorProps.onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        {/* Mounted only while open so the draft re-initialises from the saved rules. */}
        {open && <DeviceMappingEditor {...editorProps} />}
      </DialogContent>
    </Dialog>
  );
}
