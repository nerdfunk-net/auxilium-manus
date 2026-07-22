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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

import {
  customFieldRowsFromConfig,
  customFieldsToConfig,
  parseDeviceFieldsConfig,
  patchDeviceFieldSpec,
  requiredFieldSpec,
} from "./add-to-nautobot-config";
import type {
  AddToNautobotConfig,
  CustomFieldRow,
  DeviceFieldKey,
  DeviceFieldsConfig,
  InterfaceCreateConfig,
  UpdateFieldSpec,
  VirtualChassisConfig,
} from "./types";
import {
  DEVICE_FIELD_VALUE_HELP,
  OPTIONAL_DEVICE_FIELD_DEFINITIONS,
  RACK_FIELD_DEFINITIONS,
  REQUIRED_DEVICE_FIELD_DEFINITIONS,
} from "./types";

interface AddToNautobotDialogProps {
  open: boolean;
  value: AddToNautobotConfig;
  onClose: () => void;
  onChange: (value: AddToNautobotConfig) => void;
}

const EMPTY_INTERFACES: InterfaceCreateConfig[] = [];
const EMPTY_FIELD_SPEC: UpdateFieldSpec = { enabled: false, value: "" };
const DEFAULT_VIRTUAL_CHASSIS: VirtualChassisConfig = { mode: "none", id: "", name: "" };

function newInterfaceRow(): InterfaceCreateConfig {
  return { id: crypto.randomUUID(), name: "", namespace: "Global" };
}

function newCustomFieldRow(): CustomFieldRow {
  return { id: crypto.randomUUID(), name: "", enabled: true, value: "" };
}

function withInterfaceIds(
  interfaces: Array<Partial<InterfaceCreateConfig>> | undefined,
): InterfaceCreateConfig[] {
  return (interfaces ?? []).map((item) => ({
    id: item.id ?? crypto.randomUUID(),
    name: item.name ?? "",
    type: item.type,
    status: item.status,
    ip_address: item.ip_address,
    namespace: item.namespace ?? "Global",
    description: item.description,
    is_primary_ipv4: item.is_primary_ipv4,
  }));
}

function RequiredFieldRow({
  label,
  placeholder,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const isEmpty = !value.trim();
  return (
    <div
      className={`space-y-1 rounded-lg border p-2.5 ${
        isEmpty ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-slate-50"
      }`}
    >
      <Label className="text-[11px] font-medium text-muted-foreground">
        {label} <span className="text-amber-600">*</span>
      </Label>
      <Input
        className="h-8 text-xs focus-visible:ring-teal-400/40"
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function OptionalFieldRow({
  label,
  placeholder,
  spec,
  onChange,
}: {
  label: string;
  placeholder: string;
  spec: UpdateFieldSpec;
  onChange: (patch: Partial<UpdateFieldSpec>) => void;
}) {
  return (
    <div className="space-y-1 rounded-lg border border-slate-200 bg-slate-50 p-2.5">
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={spec.enabled}
          onChange={(event) => onChange({ enabled: event.target.checked })}
          className="size-4 rounded border accent-teal-500"
          aria-label={`Enable ${label}`}
        />
        <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      </div>
      <Input
        className="h-8 text-xs focus-visible:ring-teal-400/40 disabled:opacity-50"
        disabled={!spec.enabled}
        placeholder={placeholder}
        value={spec.value}
        onChange={(event) => onChange({ value: event.target.value })}
      />
    </div>
  );
}

function interfaceForSave({ id, ...rest }: InterfaceCreateConfig) {
  void id;
  return rest;
}

function buildInitialDraft(value: AddToNautobotConfig) {
  const parsedFields = parseDeviceFieldsConfig(value.device_fields);
  return {
    draft: {
      ...value,
      device_fields: parsedFields,
      interfaces: withInterfaceIds(value.interfaces as Array<Partial<InterfaceCreateConfig>>),
      virtual_chassis: { ...DEFAULT_VIRTUAL_CHASSIS, ...(value.virtual_chassis ?? {}) },
    },
    customFieldRows: customFieldRowsFromConfig(parsedFields),
  };
}

function AddToNautobotDialogForm({
  value,
  onClose,
  onChange,
}: Omit<AddToNautobotDialogProps, "open">) {
  const initial = useMemo(() => buildInitialDraft(value), [value]);
  const [draft, setDraft] = useState(initial.draft);
  const [customFieldRows, setCustomFieldRows] = useState(initial.customFieldRows);

  const deviceFields = draft.device_fields ?? ({} as DeviceFieldsConfig);
  const interfaces = draft.interfaces ?? EMPTY_INTERFACES;
  const virtualChassis = draft.virtual_chassis ?? DEFAULT_VIRTUAL_CHASSIS;

  const handleSave = () => {
    onChange({
      ...draft,
      device_fields: {
        ...deviceFields,
        custom_fields: customFieldsToConfig(customFieldRows),
      },
      interfaces: interfaces.map(interfaceForSave),
      add_prefix: draft.add_prefix ?? true,
      default_prefix_length: draft.default_prefix_length ?? "/24",
      virtual_chassis: virtualChassis,
      dry_run: draft.dry_run ?? false,
    });
    onClose();
  };

  const patchRequiredField = (key: DeviceFieldKey, text: string) => {
    setDraft((current) => ({
      ...current,
      device_fields: patchDeviceFieldSpec(current.device_fields, key, {
        enabled: true,
        value: text,
      }),
    }));
  };

  const patchOptionalField = (key: DeviceFieldKey, patch: Partial<UpdateFieldSpec>) => {
    setDraft((current) => ({
      ...current,
      device_fields: patchDeviceFieldSpec(current.device_fields, key, patch),
    }));
  };

  const patchInterface = (id: string, patch: Partial<InterfaceCreateConfig>) => {
    setDraft((current) => ({
      ...current,
      interfaces: (current.interfaces ?? EMPTY_INTERFACES).map((item) =>
        (item.id ?? item.name) === id ? { ...item, ...patch } : item,
      ),
    }));
  };

  const addInterface = () => {
    setDraft((current) => ({
      ...current,
      interfaces: [...(current.interfaces ?? EMPTY_INTERFACES), newInterfaceRow()],
    }));
  };

  const removeInterface = (id: string) => {
    setDraft((current) => ({
      ...current,
      interfaces: (current.interfaces ?? EMPTY_INTERFACES).filter(
        (item) => (item.id ?? item.name) !== id,
      ),
    }));
  };

  const patchCustomFieldRow = (id: string, patch: Partial<CustomFieldRow>) => {
    setCustomFieldRows((rows) => rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  };

  const addCustomFieldRow = () => {
    setCustomFieldRows((rows) => [...rows, newCustomFieldRow()]);
  };

  const removeCustomFieldRow = (id: string) => {
    setCustomFieldRows((rows) => rows.filter((row) => row.id !== id));
  };

  const patchVirtualChassis = (patch: Partial<VirtualChassisConfig>) => {
    setDraft((current) => ({
      ...current,
      virtual_chassis: { ...(current.virtual_chassis ?? DEFAULT_VIRTUAL_CHASSIS), ...patch },
    }));
  };

  const enabledOptionalCount =
    OPTIONAL_DEVICE_FIELD_DEFINITIONS.filter(({ key }) => deviceFields[key]?.enabled).length +
    customFieldRows.filter((row) => row.enabled && row.name.trim()).length;

  return (
    <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
      <DialogHeader className="border-b bg-gradient-to-r from-teal-600 to-teal-500 px-4 py-3 text-white">
        <DialogTitle className="text-base text-white">Add to Nautobot Configuration</DialogTitle>
      </DialogHeader>

      <div className="space-y-4 overflow-y-auto bg-slate-50 p-4">
        <section className="space-y-2 rounded-xl border border-slate-200 bg-card p-3 shadow-sm">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-medium">device_fields</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              required
            </Badge>
          </div>
          <p className="text-[11px] leading-4 text-muted-foreground">{DEVICE_FIELD_VALUE_HELP}</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {REQUIRED_DEVICE_FIELD_DEFINITIONS.map(({ key, label, placeholder }) => (
              <RequiredFieldRow
                key={key}
                label={label}
                placeholder={placeholder}
                value={requiredFieldSpec(deviceFields, key).value}
                onChange={(text) => patchRequiredField(key, text)}
              />
            ))}
          </div>
        </section>

        <section className="space-y-3 rounded-xl border border-slate-200 bg-card p-3 shadow-sm">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-medium">device_fields</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              optional
            </Badge>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {OPTIONAL_DEVICE_FIELD_DEFINITIONS.map(({ key, label, placeholder }) => (
              <OptionalFieldRow
                key={key}
                label={label}
                placeholder={placeholder}
                spec={deviceFields[key] ?? EMPTY_FIELD_SPEC}
                onChange={(patch) => patchOptionalField(key, patch)}
              />
            ))}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs font-medium">custom_fields</span>
              <Button
                className="h-7 bg-teal-500 text-white hover:bg-teal-600"
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
                  <div
                    className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-2.5"
                    key={row.id}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={row.enabled}
                          onChange={(event) =>
                            patchCustomFieldRow(row.id, { enabled: event.target.checked })
                          }
                          className="size-4 rounded border accent-teal-500"
                          aria-label={`Enable custom field ${row.name || "row"}`}
                        />
                        <span className="text-xs font-medium text-teal-700">Custom field</span>
                      </div>
                      <Button
                        className="h-7 px-2 text-destructive hover:text-destructive"
                        size="sm"
                        type="button"
                        variant="ghost"
                        onClick={() => removeCustomFieldRow(row.id)}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <Input
                        className="h-8 text-xs disabled:opacity-50"
                        disabled={!row.enabled}
                        placeholder="field_name"
                        value={row.name}
                        onChange={(event) =>
                          patchCustomFieldRow(row.id, { name: event.target.value })
                        }
                      />
                      <Input
                        className="h-8 text-xs disabled:opacity-50"
                        disabled={!row.enabled}
                        placeholder="{custom.site | default('N/A')}"
                        value={row.value}
                        onChange={(event) =>
                          patchCustomFieldRow(row.id, { value: event.target.value })
                        }
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <p className="text-[11px] text-muted-foreground">
            {enabledOptionalCount} optional field{enabledOptionalCount === 1 ? "" : "s"} enabled.
          </p>
        </section>

        <section className="space-y-2 rounded-xl border border-slate-200 bg-card p-3 shadow-sm">
          <span className="font-mono text-xs font-medium">rack</span>
          <p className="text-[11px] text-muted-foreground">
            Optional — leave rack empty to skip placement entirely.
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            {RACK_FIELD_DEFINITIONS.map(({ key, label, placeholder }) => (
              <OptionalFieldRow
                key={key}
                label={label}
                placeholder={placeholder}
                spec={deviceFields[key] ?? EMPTY_FIELD_SPEC}
                onChange={(patch) => patchOptionalField(key, patch)}
              />
            ))}
          </div>
        </section>

        <section className="space-y-3 rounded-xl border border-slate-200 bg-card p-3 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-medium">interfaces</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                object_list
              </Badge>
            </div>
            <Button
              className="h-7 bg-teal-500 text-white hover:bg-teal-600"
              size="sm"
              type="button"
              onClick={addInterface}
            >
              <Plus className="mr-1 size-3.5" />
              Add
            </Button>
          </div>

          {interfaces.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">No interfaces configured.</p>
          ) : (
            <div className="space-y-3">
              {interfaces.map((iface) => {
                const rowId = iface.id ?? iface.name;
                return (
                  <div
                    className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3"
                    key={rowId}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-teal-700">Interface</span>
                      <Button
                        className="h-7 px-2 text-destructive hover:text-destructive"
                        size="sm"
                        type="button"
                        variant="ghost"
                        onClick={() => removeInterface(rowId)}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <div className="space-y-1">
                        <Label className="text-[11px] text-muted-foreground">Name</Label>
                        <Input
                          className="h-8 text-xs"
                          value={iface.name}
                          onChange={(event) => patchInterface(rowId, { name: event.target.value })}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-[11px] text-muted-foreground">Type</Label>
                        <Input
                          className="h-8 text-xs"
                          placeholder="1000base-t"
                          value={iface.type ?? ""}
                          onChange={(event) => patchInterface(rowId, { type: event.target.value })}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-[11px] text-muted-foreground">Status</Label>
                        <Input
                          className="h-8 text-xs"
                          placeholder="active"
                          value={iface.status ?? ""}
                          onChange={(event) =>
                            patchInterface(rowId, { status: event.target.value })
                          }
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-[11px] text-muted-foreground">IP address</Label>
                        <Input
                          className="h-8 font-mono text-xs"
                          placeholder="10.0.0.1/24"
                          value={iface.ip_address ?? ""}
                          onChange={(event) =>
                            patchInterface(rowId, { ip_address: event.target.value })
                          }
                        />
                      </div>
                      <div className="space-y-1 sm:col-span-2">
                        <Label className="text-[11px] text-muted-foreground">Description</Label>
                        <Input
                          className="h-8 text-xs"
                          value={iface.description ?? ""}
                          onChange={(event) =>
                            patchInterface(rowId, { description: event.target.value })
                          }
                        />
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <Label className="text-[11px] text-muted-foreground">Primary IPv4</Label>
                      <Switch
                        checked={iface.is_primary_ipv4 ?? false}
                        onCheckedChange={(checked) =>
                          patchInterface(rowId, { is_primary_ipv4: checked })
                        }
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="space-y-3 rounded-xl border border-slate-200 bg-card p-3 shadow-sm">
          <div className="flex items-center justify-between">
            <Label className="font-mono text-xs font-medium">add_prefix</Label>
            <Switch
              checked={draft.add_prefix ?? true}
              onCheckedChange={(checked) =>
                setDraft((current) => ({ ...current, add_prefix: checked }))
              }
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">default_prefix_length</Label>
            <Input
              className="h-8 font-mono text-xs"
              value={draft.default_prefix_length ?? "/24"}
              onChange={(event) =>
                setDraft((current) => ({ ...current, default_prefix_length: event.target.value }))
              }
            />
          </div>
        </section>

        <section className="space-y-2 border-t pt-3">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs font-medium">virtual_chassis</span>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Optionally join or create a virtual chassis for this device.
          </p>
          <Select
            value={virtualChassis.mode}
            onValueChange={(mode) => patchVirtualChassis({ mode: mode as VirtualChassisConfig["mode"] })}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">None</SelectItem>
              <SelectItem value="join">Join existing virtual chassis</SelectItem>
              <SelectItem value="create">Create new virtual chassis (device = master)</SelectItem>
            </SelectContent>
          </Select>

          {virtualChassis.mode === "join" ? (
            <div className="space-y-1 pl-1">
              <Label className="text-[11px] text-muted-foreground">Virtual chassis UUID</Label>
              <Input
                className="h-8 font-mono text-xs"
                placeholder="550e8400-e29b-41d4-a716-446655440000"
                value={virtualChassis.id ?? ""}
                onChange={(event) => patchVirtualChassis({ id: event.target.value })}
              />
            </div>
          ) : null}

          {virtualChassis.mode === "create" ? (
            <div className="space-y-1 pl-1">
              <Label className="text-[11px] text-muted-foreground">New virtual chassis name</Label>
              <Input
                className="h-8 text-xs"
                placeholder="stack-1"
                value={virtualChassis.name ?? ""}
                onChange={(event) => patchVirtualChassis({ name: event.target.value })}
              />
            </div>
          ) : null}
        </section>

        <section className="space-y-2 border-t pt-3">
          <div className="flex items-center justify-between">
            <Label className="font-mono text-xs font-medium">dry_run</Label>
            <Switch
              checked={draft.dry_run ?? false}
              onCheckedChange={(checked) => setDraft((current) => ({ ...current, dry_run: checked }))}
            />
          </div>
          <p className="text-[11px] text-muted-foreground">
            When on, validates the resolved fields against Nautobot (duplicate name and UUID
            existence checks) without creating the device.
          </p>
        </section>
      </div>

      <DialogFooter className="border-t bg-white px-4 py-3">
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button className="bg-teal-500 text-white hover:bg-teal-600" type="button" onClick={handleSave}>
          Save
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

export function AddToNautobotDialog({ open, value, onClose, onChange }: AddToNautobotDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onClose();
        }
      }}
    >
      {open ? <AddToNautobotDialogForm value={value} onClose={onClose} onChange={onChange} /> : null}
    </Dialog>
  );
}
