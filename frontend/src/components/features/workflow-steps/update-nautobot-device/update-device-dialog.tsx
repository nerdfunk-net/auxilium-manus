"use client";

import { useMemo, useState } from "react";

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
import { Switch } from "@/components/ui/switch";

import { InterfacesSection } from "./interfaces-section";
import type {
  CustomFieldRow,
  DeviceFieldKey,
  DeviceIdentifierConfig,
  InterfaceUpdateConfig,
  UpdateFieldSpec,
  UpdateNautobotDeviceConfig,
} from "./types";
import {
  DeviceIdentifierSection,
  UpdateFieldsSection,
} from "./update-fields-section";
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
const EMPTY_UPDATE_FIELDS: NonNullable<UpdateNautobotDeviceConfig["update_fields"]> = {};

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

function interfaceForSave({ id, ...rest }: InterfaceUpdateConfig) {
  void id;
  return rest;
}

function buildInitialDraft(value: UpdateNautobotDeviceConfig) {
  const parsedFields = parseUpdateFieldsConfig(value.update_fields);
  return {
    draft: {
      ...value,
      update_fields: parsedFields,
      interfaces: withInterfaceIds(value.interfaces as Array<Partial<InterfaceUpdateConfig>>),
    },
    customFieldRows: customFieldRowsFromConfig(parsedFields),
  };
}

function UpdateDeviceDialogForm({
  value,
  onClose,
  onChange,
}: Omit<UpdateDeviceDialogProps, "open">) {
  const initial = useMemo(() => buildInitialDraft(value), [value]);
  const [draft, setDraft] = useState(initial.draft);
  const [customFieldRows, setCustomFieldRows] = useState(initial.customFieldRows);

  const deviceIdentifier = draft.device_identifier ?? { mode: "from_context" };
  const updateFields = draft.update_fields ?? EMPTY_UPDATE_FIELDS;
  const interfaces = draft.interfaces ?? EMPTY_INTERFACES;

  const handleSave = () => {
    onChange({
      ...draft,
      device_identifier: deviceIdentifier,
      update_fields: {
        ...updateFields,
        custom_fields: customFieldsToConfig(customFieldRows),
      },
      interfaces: interfaces.map(interfaceForSave),
      add_prefix: draft.add_prefix ?? true,
      default_prefix_length: draft.default_prefix_length ?? "/24",
      sync_interfaces: draft.sync_interfaces ?? false,
    });
    onClose();
  };

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
    <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b step-header px-4 py-3">
          <DialogTitle className="text-base text-step-header-foreground">Update Device Configuration</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 overflow-y-auto bg-muted p-4">
          <DeviceIdentifierSection
            deviceIdentifier={deviceIdentifier}
            onPatchIdentifier={patchIdentifier}
          />

          <UpdateFieldsSection
            customFieldRows={customFieldRows}
            updateFields={updateFields}
            onAddCustomFieldRow={addCustomFieldRow}
            onPatchCustomFieldRow={patchCustomFieldRow}
            onPatchField={patchField}
            onRemoveCustomFieldRow={removeCustomFieldRow}
          />

          <InterfacesSection
            interfaces={interfaces}
            onAddInterface={addInterface}
            onPatchInterface={patchInterface}
            onRemoveInterface={removeInterface}
          />

          <section className="space-y-3 rounded-xl border border-border bg-card p-3 shadow-sm">
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

export function UpdateDeviceDialog({
  open,
  value,
  onClose,
  onChange,
}: UpdateDeviceDialogProps) {
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
        <UpdateDeviceDialogForm value={value} onClose={onClose} onChange={onChange} />
      ) : null}
    </Dialog>
  );
}
