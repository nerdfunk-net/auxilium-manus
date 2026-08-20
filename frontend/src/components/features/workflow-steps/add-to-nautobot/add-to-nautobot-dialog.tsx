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

import {
  customFieldRowsFromConfig,
  customFieldsSourceFromConfig,
  customFieldsToConfig,
  interfacesSourceFromConfig,
  parseDeviceFieldsConfig,
  patchDeviceFieldSpec,
} from "./add-to-nautobot-config";
import { CustomFieldsSection } from "./custom-fields-section";
import {
  OptionalDeviceFieldsSection,
  RackFieldsSection,
  RequiredDeviceFieldsSection,
} from "./device-fields-section";
import { InterfacesSection } from "./interfaces-section";
import type {
  AddToNautobotConfig,
  CustomFieldRow,
  CustomFieldsSource,
  DeviceFieldKey,
  DeviceFieldsConfig,
  InterfaceCreateConfig,
  InterfacesSource,
  UpdateFieldSpec,
  VirtualChassisConfig,
} from "./types";
import { OPTIONAL_DEVICE_FIELD_DEFINITIONS } from "./types";
import { VirtualChassisSection } from "./virtual-chassis-section";

interface AddToNautobotDialogProps {
  open: boolean;
  value: AddToNautobotConfig;
  onClose: () => void;
  onChange: (value: AddToNautobotConfig) => void;
}

const EMPTY_INTERFACES: InterfaceCreateConfig[] = [];
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

function interfaceForSave({ id, ...rest }: InterfaceCreateConfig) {
  void id;
  return rest;
}

function buildInitialDraft(value: AddToNautobotConfig) {
  const parsedFields = parseDeviceFieldsConfig(value.device_fields);
  const rawConfig = value as Record<string, unknown>;
  return {
    draft: {
      ...value,
      device_fields: parsedFields,
      custom_fields_source: customFieldsSourceFromConfig(rawConfig),
      interfaces: withInterfaceIds(value.interfaces as Array<Partial<InterfaceCreateConfig>>),
      interfaces_source: interfacesSourceFromConfig(rawConfig),
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
  const customFieldsSource = draft.custom_fields_source ?? "manual";
  const interfacesSource = draft.interfaces_source ?? "manual";

  const handleSave = () => {
    onChange({
      ...draft,
      device_fields: {
        ...deviceFields,
        custom_fields: customFieldsToConfig(customFieldRows),
      },
      custom_fields_source: customFieldsSource,
      interfaces: interfaces.map(interfaceForSave),
      interfaces_source: interfacesSource,
      add_prefix: draft.add_prefix ?? true,
      default_prefix_length: draft.default_prefix_length ?? "/24",
      virtual_chassis: virtualChassis,
      dry_run: draft.dry_run ?? false,
    });
    onClose();
  };

  const setCustomFieldsSource = (source: CustomFieldsSource) => {
    setDraft((current) => ({ ...current, custom_fields_source: source }));
  };

  const setInterfacesSource = (source: InterfacesSource) => {
    setDraft((current) => ({ ...current, interfaces_source: source }));
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
    (customFieldsSource === "manual"
      ? customFieldRows.filter((row) => row.enabled && row.name.trim()).length
      : 0);

  return (
    <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
      <DialogHeader className="border-b step-header px-4 py-3">
        <DialogTitle className="text-base text-step-header-foreground">Add to Nautobot Configuration</DialogTitle>
      </DialogHeader>

      <div className="space-y-4 overflow-y-auto bg-muted p-4">
        <RequiredDeviceFieldsSection
          deviceFields={deviceFields}
          onPatchRequiredField={patchRequiredField}
        />

        <OptionalDeviceFieldsSection
          deviceFields={deviceFields}
          enabledOptionalCount={enabledOptionalCount}
          onPatchOptionalField={patchOptionalField}
        >
          <CustomFieldsSection
            customFieldRows={customFieldRows}
            customFieldsSource={customFieldsSource}
            onAddRow={addCustomFieldRow}
            onPatchRow={patchCustomFieldRow}
            onRemoveRow={removeCustomFieldRow}
            onSourceChange={setCustomFieldsSource}
          />
        </OptionalDeviceFieldsSection>

        <RackFieldsSection deviceFields={deviceFields} onPatchOptionalField={patchOptionalField} />

        <InterfacesSection
          interfaces={interfaces}
          interfacesSource={interfacesSource}
          onAddInterface={addInterface}
          onPatchInterface={patchInterface}
          onRemoveInterface={removeInterface}
          onSourceChange={setInterfacesSource}
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
                setDraft((current) => ({ ...current, default_prefix_length: event.target.value }))
              }
            />
          </div>
        </section>

        <VirtualChassisSection virtualChassis={virtualChassis} onPatch={patchVirtualChassis} />

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

      <DialogFooter className="border-t bg-card px-4 py-3">
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button className="bg-step text-step-foreground hover:bg-step-hover" type="button" onClick={handleSave}>
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
