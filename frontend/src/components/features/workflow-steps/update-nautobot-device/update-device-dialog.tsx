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
import { Textarea } from "@/components/ui/textarea";

import type {
  DeviceIdentifierConfig,
  DeviceUpdateFields,
  InterfaceUpdateConfig,
  UpdateNautobotDeviceConfig,
} from "./types";
import { DEVICE_FIELD_DEFINITIONS } from "./types";

interface UpdateDeviceDialogProps {
  open: boolean;
  value: UpdateNautobotDeviceConfig;
  onClose: () => void;
  onChange: (value: UpdateNautobotDeviceConfig) => void;
}

const EMPTY_FIELDS: DeviceUpdateFields = {};
const EMPTY_INTERFACES: InterfaceUpdateConfig[] = [];

function parseTagsInput(raw: string): string[] {
  return raw
    .split(/[,;\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatTagsInput(tags: string[] | undefined): string {
  return (tags ?? []).join(", ");
}

function parseCustomFields(raw: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || !trimmed.includes("=")) continue;
    const [key, ...rest] = trimmed.split("=");
    const value = rest.join("=").trim();
    if (key.trim() && value) {
      result[key.trim()] = value;
    }
  }
  return result;
}

function formatCustomFields(fields: Record<string, string> | undefined): string {
  if (!fields) return "";
  return Object.entries(fields)
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
}

function newInterfaceRow(): InterfaceUpdateConfig {
  return {
    id: crypto.randomUUID(),
    name: "",
    namespace: "Global",
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

export function UpdateDeviceDialog({
  open,
  value,
  onClose,
  onChange,
}: UpdateDeviceDialogProps) {
  const [draft, setDraft] = useState<UpdateNautobotDeviceConfig>(value);

  const deviceIdentifier = draft.device_identifier ?? { mode: "from_context" };
  const updateFields = draft.update_fields ?? EMPTY_FIELDS;
  const interfaces = draft.interfaces ?? EMPTY_INTERFACES;

  const resetDraft = useCallback(() => {
    setDraft({
      ...value,
      interfaces: withInterfaceIds(value.interfaces as Array<Partial<InterfaceUpdateConfig>>),
    });
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
      update_fields: updateFields,
      interfaces: interfaces.map(({ id: _id, ...rest }) => rest),
      add_prefix: draft.add_prefix ?? true,
      default_prefix_length: draft.default_prefix_length ?? "/24",
      sync_interfaces: draft.sync_interfaces ?? false,
    });
    onClose();
  };

  const configuredFieldCount = useMemo(
    () =>
      DEVICE_FIELD_DEFINITIONS.filter(({ key }) => {
        const fieldValue = updateFields[key as keyof DeviceUpdateFields];
        return typeof fieldValue === "string" ? fieldValue.trim().length > 0 : Boolean(fieldValue);
      }).length,
    [updateFields],
  );

  const patchIdentifier = (patch: Partial<DeviceIdentifierConfig>) => {
    setDraft((current) => ({
      ...current,
      device_identifier: { ...deviceIdentifier, ...patch },
    }));
  };

  const patchField = (key: keyof DeviceUpdateFields, fieldValue: string) => {
    setDraft((current) => ({
      ...current,
      update_fields: {
        ...(current.update_fields ?? EMPTY_FIELDS),
        [key]: fieldValue,
      },
    }));
  };

  const patchInterface = (id: string, patch: Partial<InterfaceUpdateConfig>) => {
    setDraft((current) => ({
      ...current,
      interfaces: (current.interfaces ?? EMPTY_INTERFACES).map((item) =>
        item.id === id ? { ...item, ...patch } : item,
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
      interfaces: (current.interfaces ?? EMPTY_INTERFACES).filter((item) => item.id !== id),
    }));
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
            <div className="grid gap-2 sm:grid-cols-2">
              {DEVICE_FIELD_DEFINITIONS.map(({ key, label }) => (
                <div className="space-y-1" key={key}>
                  <Label className="text-[11px] text-muted-foreground">{label}</Label>
                  <Input
                    className="h-8 text-xs focus-visible:ring-teal-400/40"
                    placeholder={`${label} (optional)`}
                    value={(updateFields[key as keyof DeviceUpdateFields] as string | undefined) ?? ""}
                    onChange={(event) =>
                      patchField(key as keyof DeviceUpdateFields, event.target.value)
                    }
                  />
                </div>
              ))}
            </div>
            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">Tags</Label>
              <Input
                className="h-8 text-xs focus-visible:ring-teal-400/40"
                placeholder="tag1, tag2"
                value={formatTagsInput(updateFields.tags)}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    update_fields: {
                      ...(current.update_fields ?? EMPTY_FIELDS),
                      tags: parseTagsInput(event.target.value),
                    },
                  }))
                }
              />
            </div>
            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">Custom fields</Label>
              <Textarea
                className="min-h-[72px] font-mono text-xs focus-visible:ring-teal-400/40"
                placeholder={"field_a=value\nfield_b=value"}
                value={formatCustomFields(updateFields.custom_fields)}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    update_fields: {
                      ...(current.update_fields ?? EMPTY_FIELDS),
                      custom_fields: parseCustomFields(event.target.value),
                    },
                  }))
                }
              />
            </div>
            <p className="text-[11px] text-muted-foreground">
              {configuredFieldCount} device field{configuredFieldCount === 1 ? "" : "s"} configured.
              Empty fields are not sent to Nautobot.
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
                {interfaces.map((iface) => (
                  <div
                    className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3"
                    key={iface.id}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-teal-700">Interface</span>
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
                          value={iface.name}
                          onChange={(event) =>
                            patchInterface(iface.id, { name: event.target.value })
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
                            patchInterface(iface.id, { type: event.target.value })
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
                            patchInterface(iface.id, { status: event.target.value })
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
                            patchInterface(iface.id, { ip_address: event.target.value })
                          }
                        />
                      </div>
                      <div className="space-y-1 sm:col-span-2">
                        <Label className="text-[11px] text-muted-foreground">Description</Label>
                        <Input
                          className="h-8 text-xs"
                          value={iface.description ?? ""}
                          onChange={(event) =>
                            patchInterface(iface.id, { description: event.target.value })
                          }
                        />
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <Label className="text-[11px] text-muted-foreground">Primary IPv4</Label>
                      <Switch
                        checked={iface.is_primary_ipv4 ?? false}
                        onCheckedChange={(checked) =>
                          patchInterface(iface.id, { is_primary_ipv4: checked })
                        }
                      />
                    </div>
                  </div>
                ))}
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
