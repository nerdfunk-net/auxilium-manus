"use client";

import { Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

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

import type {
  CustomFieldRow,
  DeviceFieldKey,
  DeviceIdentifierConfig,
  InterfaceUpdateConfig,
  UpdateFieldSpec,
  UpdateNautobotDeviceConfig,
} from "./types";
import { DEVICE_FIELD_DEFINITIONS, UPDATE_FIELD_VALUE_HELP } from "./types";
import {
  customFieldRowsFromConfig,
  customFieldsToConfig,
  parseUpdateFieldsConfig,
  patchDeviceFieldSpec,
} from "./update-device-config";

interface UpdateDeviceDialogProps {
  open: boolean;
  value: UpdateNautobotDeviceConfig;
  onClose: () => void;
  onChange: (value: UpdateNautobotDeviceConfig) => void;
}

const EMPTY_INTERFACES: InterfaceUpdateConfig[] = [];
const EMPTY_FIELD_SPEC: UpdateFieldSpec = { enabled: false, value: "" };

function newInterfaceRow(): InterfaceUpdateConfig {
  return {
    id: crypto.randomUUID(),
    name: "",
    namespace: "Global",
  };
}

function newCustomFieldRow(): CustomFieldRow {
  return {
    id: crypto.randomUUID(),
    name: "",
    enabled: true,
    value: "",
  };
}

function withInterfaceIds(
  interfaces: Array<Partial<InterfaceUpdateConfig>> | undefined,
): InterfaceUpdateConfig[] {
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

function FieldRow({
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

export function UpdateDeviceDialog({
  open,
  value,
  onClose,
  onChange,
}: UpdateDeviceDialogProps) {
  const [draft, setDraft] = useState<UpdateNautobotDeviceConfig>(value);
  const [customFieldRows, setCustomFieldRows] = useState<CustomFieldRow[]>([]);

  const deviceIdentifier = draft.device_identifier ?? { mode: "from_context" };
  const updateFields = draft.update_fields ?? {};
  const interfaces = draft.interfaces ?? EMPTY_INTERFACES;

  const resetDraft = useCallback(() => {
    const parsedFields = parseUpdateFieldsConfig(value.update_fields);
    setDraft({
      ...value,
      update_fields: parsedFields,
      interfaces: withInterfaceIds(value.interfaces as Array<Partial<InterfaceUpdateConfig>>),
    });
    setCustomFieldRows(customFieldRowsFromConfig(parsedFields));
  }, [value]);

  useEffect(() => {
    if (open) {
      resetDraft();
    }
  }, [open, resetDraft]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      onClose();
    }
  };

  const handleSave = () => {
    onChange({
      ...draft,
      device_identifier: deviceIdentifier,
      update_fields: {
        ...updateFields,
        custom_fields: customFieldsToConfig(customFieldRows),
      },
      interfaces: interfaces.map(({ id: _id, ...rest }) => rest),
      add_prefix: draft.add_prefix ?? true,
      default_prefix_length: draft.default_prefix_length ?? "/24",
      sync_interfaces: draft.sync_interfaces ?? false,
    });
    onClose();
  };

  const enabledFieldCount = useMemo(() => {
    const baseCount = DEVICE_FIELD_DEFINITIONS.filter(({ key }) => updateFields[key]?.enabled).length;
    const customCount = customFieldRows.filter((row) => row.enabled && row.name.trim()).length;
    return baseCount + customCount;
  }, [updateFields, customFieldRows]);

  const patchIdentifier = (patch: Partial<DeviceIdentifierConfig>) => {
    setDraft((current) => ({
      ...current,
      device_identifier: { ...deviceIdentifier, ...patch },
    }));
  };

  const patchField = (key: DeviceFieldKey, patch: Partial<UpdateFieldSpec>) => {
    setDraft((current) => ({
      ...current,
      update_fields: patchDeviceFieldSpec(current.update_fields, key, patch),
    }));
  };

  const patchInterface = (id: string, patch: Partial<InterfaceUpdateConfig>) => {
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
    setCustomFieldRows((rows) =>
      rows.map((row) => (row.id === id ? { ...row, ...patch } : row)),
    );
  };

  const addCustomFieldRow = () => {
    setCustomFieldRows((rows) => [...rows, newCustomFieldRow()]);
  };

  const removeCustomFieldRow = (id: string) => {
    setCustomFieldRows((rows) => rows.filter((row) => row.id !== id));
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b bg-gradient-to-r from-teal-600 to-teal-500 px-4 py-3 text-white">
          <DialogTitle className="text-base text-white">Update Device Configuration</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 overflow-y-auto bg-slate-50 p-4">
          <section className="space-y-2 rounded-xl border border-slate-200 bg-card p-3 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-medium">device_identifier</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                object
              </Badge>
            </div>
            <Select
              value={deviceIdentifier.mode}
              onValueChange={(mode) =>
                patchIdentifier({ mode: mode as DeviceIdentifierConfig["mode"] })
              }
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="from_context">From workflow context</SelectItem>
                <SelectItem value="explicit">Explicit UUID or name</SelectItem>
              </SelectContent>
            </Select>
            {deviceIdentifier.mode === "explicit" ? (
              <div className="grid gap-2 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label className="text-[11px] text-muted-foreground">Device UUID</Label>
                  <Input
                    className="h-8 font-mono text-xs"
                    placeholder="550e8400-e29b-41d4-a716-446655440000"
                    value={deviceIdentifier.id ?? ""}
                    onChange={(event) => patchIdentifier({ id: event.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-[11px] text-muted-foreground">Device name</Label>
                  <Input
                    className="h-8 text-xs"
                    placeholder="router1"
                    value={deviceIdentifier.name ?? ""}
                    onChange={(event) => patchIdentifier({ name: event.target.value })}
                  />
                </div>
              </div>
            ) : (
              <p className="text-[11px] text-muted-foreground">
                Uses each device from the upstream inventory step (UUID or name).
              </p>
            )}
          </section>

          <section className="space-y-3 rounded-xl border border-slate-200 bg-card p-3 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-medium">update_fields</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                object
              </Badge>
            </div>
            <p className="text-[11px] leading-4 text-muted-foreground">{UPDATE_FIELD_VALUE_HELP}</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {DEVICE_FIELD_DEFINITIONS.map(({ key, label, placeholder }) => (
                <FieldRow
                  key={key}
                  label={label}
                  placeholder={placeholder}
                  spec={updateFields[key] ?? EMPTY_FIELD_SPEC}
                  onChange={(patch) => patchField(key, patch)}
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
              {enabledFieldCount} enabled field{enabledFieldCount === 1 ? "" : "s"}. Disabled
              fields are not sent to Nautobot.
            </p>
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
                          onChange={(event) =>
                            patchInterface(rowId, { name: event.target.value })
                          }
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-[11px] text-muted-foreground">Type</Label>
                        <Input
                          className="h-8 text-xs"
                          placeholder="1000base-t"
                          value={iface.type ?? ""}
                          onChange={(event) =>
                            patchInterface(rowId, { type: event.target.value })
                          }
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
                  setDraft((current) => ({
                    ...current,
                    default_prefix_length: event.target.value,
                  }))
                }
              />
            </div>
            <div className="flex items-center justify-between">
              <Label className="font-mono text-xs font-medium">sync_interfaces</Label>
              <Switch
                checked={draft.sync_interfaces ?? false}
                onCheckedChange={(checked) =>
                  setDraft((current) => ({ ...current, sync_interfaces: checked }))
                }
              />
            </div>
          </section>
        </div>

        <DialogFooter className="border-t bg-white px-4 py-3">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            className="bg-teal-500 text-white hover:bg-teal-600"
            type="button"
            onClick={handleSave}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
