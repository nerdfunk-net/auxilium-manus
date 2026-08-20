"use client";

import { Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  NautobotCustomFieldRow,
  NautobotOptionalFieldRow,
} from "@/components/features/workflow-steps/shared/nautobot-field-rows";

import {
  customFieldRowsFromConfig,
  customFieldsToConfig,
  newInterfaceRow,
  parseAttributesConfig,
  patchFieldSpec,
} from "./set-default-attributes-config";
import type {
  AttributeFieldSpec,
  AttributesConfig,
  CustomFieldRow,
  InterfaceDefaultSpec,
} from "./types";
import { OPTIONAL_ATTRIBUTE_FIELD_DEFINITIONS, RACK_FIELD_DEFINITIONS } from "./types";

interface SetDefaultAttributesDialogProps {
  open: boolean;
  value: Record<string, unknown>;
  onClose: () => void;
  onChange: (attributes: AttributesConfig) => void;
}

function ipAddressesToText(ipAddresses: string[]): string {
  return ipAddresses.join(", ");
}

function textToIpAddresses(text: string): string[] {
  return text
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

function SetDefaultAttributesDialogForm({
  value,
  onClose,
  onChange,
}: Omit<SetDefaultAttributesDialogProps, "open">) {
  const initial = useMemo(() => parseAttributesConfig(value), [value]);
  const [draft, setDraft] = useState<AttributesConfig>(initial);
  const [customFieldRows, setCustomFieldRows] = useState<CustomFieldRow[]>(() =>
    customFieldRowsFromConfig(initial),
  );

  const patchScalar = (key: keyof AttributesConfig, patch: Partial<AttributeFieldSpec>) => {
    setDraft((current) => patchFieldSpec(current, key, patch));
  };

  const patchDeviceType = (patch: Partial<AttributesConfig["device_type"]>) => {
    setDraft((current) => ({ ...current, device_type: { ...current.device_type, ...patch } }));
  };

  const patchInterface = (id: string, patch: Partial<InterfaceDefaultSpec>) => {
    setDraft((current) => ({
      ...current,
      interfaces: current.interfaces.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    }));
  };

  const addInterface = () => {
    setDraft((current) => ({ ...current, interfaces: [...current.interfaces, newInterfaceRow()] }));
  };

  const removeInterface = (id: string) => {
    setDraft((current) => ({
      ...current,
      interfaces: current.interfaces.filter((item) => item.id !== id),
    }));
  };

  const patchCustomFieldRow = (id: string, patch: Partial<CustomFieldRow>) => {
    setCustomFieldRows((rows) => rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  };

  const addCustomFieldRow = () => {
    setCustomFieldRows((rows) => [
      ...rows,
      { id: crypto.randomUUID(), name: "", enabled: true, value: "" },
    ]);
  };

  const removeCustomFieldRow = (id: string) => {
    setCustomFieldRows((rows) => rows.filter((row) => row.id !== id));
  };

  const handleSave = () => {
    onChange({
      ...draft,
      custom_fields: customFieldsToConfig(customFieldRows),
      interfaces: draft.interfaces.filter((iface) => iface.name.trim()),
    });
    onClose();
  };

  return (
    <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
      <DialogHeader className="border-b step-header px-4 py-3">
        <DialogTitle className="text-base text-step-header-foreground">Default Attributes</DialogTitle>
      </DialogHeader>

      <div className="space-y-4 overflow-y-auto bg-muted p-4">
        <section className="space-y-3 rounded-xl border border-border bg-card p-3 shadow-sm">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-medium">attributes</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              optional
            </Badge>
          </div>
          <p className="text-[11px] leading-4 text-muted-foreground">
            Only enabled fields with a value are applied — each fills the matching gap in a
            device&apos;s Nautobot attribute bag (or replaces it, if Overwrite is on).
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {OPTIONAL_ATTRIBUTE_FIELD_DEFINITIONS.map(({ key, label, placeholder }) => (
              <NautobotOptionalFieldRow
                key={key}
                label={label}
                placeholder={placeholder}
                spec={draft[key]}
                onChange={(patch) => patchScalar(key, patch)}
              />
            ))}
          </div>
        </section>

        <section className="space-y-2 rounded-xl border border-border bg-card p-3 shadow-sm">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={draft.device_type.enabled}
              onChange={(event) => patchDeviceType({ enabled: event.target.checked })}
              className="size-4 rounded border accent-step"
              aria-label="Enable device_type"
            />
            <span className="font-mono text-xs font-medium">device_type</span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">Model</Label>
              <Input
                className="h-8 text-xs disabled:opacity-50"
                disabled={!draft.device_type.enabled}
                placeholder="C9300-24T"
                value={draft.device_type.model}
                onChange={(event) => patchDeviceType({ model: event.target.value })}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">Manufacturer</Label>
              <Input
                className="h-8 text-xs disabled:opacity-50"
                disabled={!draft.device_type.enabled}
                placeholder="Cisco"
                value={draft.device_type.manufacturer}
                onChange={(event) => patchDeviceType({ manufacturer: event.target.value })}
              />
            </div>
          </div>
        </section>

        <section className="space-y-2 rounded-xl border border-border bg-card p-3 shadow-sm">
          <span className="font-mono text-xs font-medium">rack</span>
          <p className="text-[11px] text-muted-foreground">
            Optional — leave empty to skip default rack placement entirely.
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            {RACK_FIELD_DEFINITIONS.map(({ key, label, placeholder }) => (
              <NautobotOptionalFieldRow
                key={key}
                label={label}
                placeholder={placeholder}
                spec={draft[key]}
                onChange={(patch) => patchScalar(key, patch)}
              />
            ))}
          </div>
        </section>

        <section className="space-y-3 rounded-xl border border-border bg-card p-3 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-xs font-medium">custom_fields</span>
            <Button
              className="h-7 bg-step text-step-foreground hover:bg-step-hover"
              size="sm"
              type="button"
              onClick={addCustomFieldRow}
            >
              <Plus className="mr-1 size-3.5" />
              Add
            </Button>
          </div>
          {customFieldRows.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">No custom fields configured.</p>
          ) : (
            <div className="space-y-2">
              {customFieldRows.map((row) => (
                <NautobotCustomFieldRow
                  key={row.id}
                  row={row}
                  valuePlaceholder="lab"
                  onChange={(patch) => patchCustomFieldRow(row.id, patch)}
                  onRemove={() => removeCustomFieldRow(row.id)}
                />
              ))}
            </div>
          )}
        </section>

        <section className="space-y-3 rounded-xl border border-border bg-card p-3 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-medium">interfaces</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                object_list
              </Badge>
            </div>
            <Button
              className="h-7 bg-step text-step-foreground hover:bg-step-hover"
              size="sm"
              type="button"
              onClick={addInterface}
            >
              <Plus className="mr-1 size-3.5" />
              Add
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Matched by name — Add to Nautobot / Update Device don&apos;t read these back yet
            (see Help), but they still seed the bag for inspection and future use.
          </p>

          {draft.interfaces.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">No interfaces configured.</p>
          ) : (
            <div className="space-y-3">
              {draft.interfaces.map((iface) => (
                <div
                  className="space-y-2 rounded-lg border border-border bg-muted p-3"
                  key={iface.id}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium text-step-muted-foreground">Interface</span>
                    <Button
                      className="h-7 px-2 text-destructive hover:text-destructive"
                      size="sm"
                      type="button"
                      variant="ghost"
                      onClick={() => removeInterface(iface.id)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="space-y-1">
                      <Label className="text-[11px] text-muted-foreground">Name</Label>
                      <Input
                        className="h-8 text-xs"
                        placeholder="Ethernet0/0"
                        value={iface.name}
                        onChange={(event) => patchInterface(iface.id, { name: event.target.value })}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px] text-muted-foreground">Type</Label>
                      <Input
                        className="h-8 text-xs"
                        placeholder="VIRTUAL"
                        value={iface.type}
                        onChange={(event) => patchInterface(iface.id, { type: event.target.value })}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px] text-muted-foreground">Status</Label>
                      <Input
                        className="h-8 text-xs"
                        placeholder="Active"
                        value={iface.status}
                        onChange={(event) => patchInterface(iface.id, { status: event.target.value })}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px] text-muted-foreground">IP addresses</Label>
                      <Input
                        className="h-8 font-mono text-xs"
                        placeholder="192.168.178.240/24, 10.0.0.1/24"
                        value={ipAddressesToText(iface.ip_addresses)}
                        onChange={(event) =>
                          patchInterface(iface.id, {
                            ip_addresses: textToIpAddresses(event.target.value),
                          })
                        }
                      />
                    </div>
                    <div className="space-y-1 sm:col-span-2">
                      <Label className="text-[11px] text-muted-foreground">Description</Label>
                      <Input
                        className="h-8 text-xs"
                        value={iface.description}
                        onChange={(event) =>
                          patchInterface(iface.id, { description: event.target.value })
                        }
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <DialogFooter className="border-t bg-card px-4 py-3">
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button
          className="bg-step text-step-foreground hover:bg-step-hover"
          type="button"
          onClick={handleSave}
        >
          Save
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

export function SetDefaultAttributesDialog({
  open,
  value,
  onClose,
  onChange,
}: SetDefaultAttributesDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onClose();
        }
      }}
    >
      {open ? (
        <SetDefaultAttributesDialogForm value={value} onClose={onClose} onChange={onChange} />
      ) : null}
    </Dialog>
  );
}
