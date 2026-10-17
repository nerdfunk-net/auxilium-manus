"use client";

import { Plus, Trash2 } from "lucide-react";
import { useCallback, useId, useMemo, useState } from "react";

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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  CUSTOM_FIELD_OPTION,
  CUSTOM_FIELD_PREFIX,
  customFieldName,
  IGNORE_TARGET,
  isCustomFieldTarget,
  NAUTOBOT_TARGETS,
  targetLabel,
  type NautobotTarget,
} from "./constants/nautobot-targets";
import type { FileFormat } from "./utils/file-options";
import {
  cleanMapping,
  DEFAULT_MAPPING,
  hasMappingErrors,
  mappingFromKeys,
  validateMapping,
  type DeviceMappingRule,
} from "./utils/device-mapping";

const EMPTY_KEYS: readonly string[] = [];

/** Attribute groups in catalog order (Device, Network, Role, ...). */
const TARGET_GROUPS: { group: string; targets: NautobotTarget[] }[] = NAUTOBOT_TARGETS.reduce<
  { group: string; targets: NautobotTarget[] }[]
>((groups, target) => {
  const existing = groups.find((entry) => entry.group === target.group);
  if (existing) {
    existing.targets.push(target);
    return groups;
  }
  return [...groups, { group: target.group, targets: [target] }];
}, []);

const NEW_ROW: DeviceMappingRule = { source: "", target: "" };

interface DeviceMappingDialogProps {
  open: boolean;
  rules: readonly DeviceMappingRule[];
  fileFormat: FileFormat;
  /** File keys discovered by the last preview; used as suggestions. */
  availableKeys?: readonly string[];
  loadingKeys: boolean;
  canLoadKeys: boolean;
  /** Fetches the keys/columns of the matching files; null when loading failed. */
  onLoadKeys: () => Promise<string[] | null>;
  onClose: () => void;
  onSave: (rules: DeviceMappingRule[]) => void;
}

type EditorProps = Omit<DeviceMappingDialogProps, "open">;

function DeviceMappingEditor({
  rules,
  fileFormat,
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
  const handleLoadKeys = useCallback(async () => {
    const keys = await onLoadKeys();
    if (keys) {
      setDraft((rows) => mappingFromKeys(rows, keys));
    }
  }, [onLoadKeys]);
  const resetToDefault = useCallback(() => setDraft([...DEFAULT_MAPPING]), []);

  const handleSave = useCallback(() => {
    if (hasMappingErrors(errors)) {
      setShowErrors(true);
      return;
    }
    onSave(cleanMapping(draft));
  }, [draft, errors, onSave]);

  const usedTargets = useMemo(() => new Set(draft.map((row) => row.target)), [draft]);
  const keyLabel = fileFormat === "csv" ? "Column" : "File key";
  const implicitCustomFields = useMemo(
    () =>
      availableKeys.filter(
        (key) =>
          key.startsWith("cf_") &&
          key.length > 3 &&
          !draft.some((row) => row.source === key),
      ),
    [availableKeys, draft],
  );

  return (
    <>
      <DialogHeader>
        <DialogTitle>Device Mapping</DialogTitle>
        <DialogDescription>
          {fileFormat === "csv"
            ? "Map the columns of the CSV file to Nautobot attributes."
            : "Map keys of each device entry in the file to Nautobot attributes. Nested keys can be written as parent.child."}{" "}
          Columns or keys named{" "}
          <code className="font-mono text-xs">cf_&lt;name&gt;</code> are mapped to the custom
          field <code className="font-mono text-xs">&lt;name&gt;</code> automatically.
        </DialogDescription>
      </DialogHeader>

      <datalist id={listId}>
        {availableKeys.map((key) => (
          <option key={key} value={key} />
        ))}
      </datalist>

      <div className="flex flex-col gap-2">
        <div className="grid grid-cols-[1fr_1fr_auto] gap-2 text-xs font-medium text-muted-foreground">
          <span>{keyLabel}</span>
          <span>Nautobot attribute</span>
          <span className="w-8" />
        </div>
        {draft.map((row, index) => {
          const rowError = showErrors ? errors.rows[index] : undefined;
          return (
            <div key={index} className="flex flex-col gap-1">
              <div className="grid grid-cols-[1fr_1fr_auto] items-start gap-2">
                <Input
                  aria-label={`${keyLabel} ${index + 1}`}
                  className="h-8 font-mono text-xs"
                  list={listId}
                  placeholder="device_name"
                  value={row.source}
                  onChange={(e) => updateRow(index, { source: e.target.value })}
                />
                <div className="flex flex-col gap-1">
                  <Select
                    value={
                      (isCustomFieldTarget(row.target) ? CUSTOM_FIELD_OPTION : row.target) ||
                      undefined
                    }
                    onValueChange={(target) =>
                      updateRow(index, {
                        target:
                          target === CUSTOM_FIELD_OPTION && !isCustomFieldTarget(row.target)
                            ? CUSTOM_FIELD_PREFIX
                            : target,
                      })
                    }
                  >
                    <SelectTrigger
                      aria-label={`Nautobot attribute ${index + 1}`}
                      className="h-8 text-xs"
                    >
                      <SelectValue placeholder="Select attribute…">
                        {row.target ? targetLabel(row.target) : undefined}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent className="max-h-72">
                      <SelectItem value={IGNORE_TARGET}>{targetLabel(IGNORE_TARGET)}</SelectItem>
                      {TARGET_GROUPS.map(({ group, targets }) => (
                        <SelectGroup key={group}>
                          <SelectLabel>{group}</SelectLabel>
                          {targets.map((target) => (
                            <SelectItem
                              key={target.value}
                              disabled={usedTargets.has(target.value) && target.value !== row.target}
                              value={target.value}
                            >
                              {target.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      ))}
                      <SelectGroup>
                        <SelectLabel>Custom</SelectLabel>
                        <SelectItem value={CUSTOM_FIELD_OPTION}>Custom field…</SelectItem>
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  {isCustomFieldTarget(row.target) && (
                    <Input
                      aria-label={`Custom field name ${index + 1}`}
                      className="h-8 font-mono text-xs"
                      placeholder="snmp_credentials"
                      value={customFieldName(row.target)}
                      onChange={(e) =>
                        updateRow(index, { target: `${CUSTOM_FIELD_PREFIX}${e.target.value.trim()}` })
                      }
                    />
                  )}
                </div>
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
        {implicitCustomFields.length > 0 && (
          <p className="text-[11px] text-muted-foreground">
            Custom fields mapped automatically:{" "}
            {implicitCustomFields
              .map((key) => `${key} → ${key.slice(3)}`)
              .join(", ")}
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
          onClick={handleLoadKeys}
        >
          {loadingKeys ? "Loading keys…" : "Load keys from repository"}
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
