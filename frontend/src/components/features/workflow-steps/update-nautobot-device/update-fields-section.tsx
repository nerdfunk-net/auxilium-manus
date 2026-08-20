"use client";

import { Plus } from "lucide-react";
import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  NautobotCustomFieldRow,
  NautobotOptionalFieldRow,
} from "@/components/features/workflow-steps/shared/nautobot-field-rows";

import type {
  CustomFieldRow,
  DeviceFieldKey,
  DeviceIdentifierConfig,
  UpdateFieldSpec,
} from "./types";
import { DEVICE_FIELD_DEFINITIONS, UPDATE_FIELD_VALUE_HELP } from "./types";

const EMPTY_FIELD_SPEC: UpdateFieldSpec = { enabled: false, value: "" };

interface DeviceIdentifierSectionProps {
  deviceIdentifier: DeviceIdentifierConfig;
  onPatchIdentifier: (patch: Partial<DeviceIdentifierConfig>) => void;
}

export function DeviceIdentifierSection({
  deviceIdentifier,
  onPatchIdentifier,
}: DeviceIdentifierSectionProps) {
  return (
    <section className="space-y-2 rounded-xl border border-border bg-card p-3 shadow-sm">
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs font-medium">device_identifier</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          object
        </Badge>
      </div>
      <Select
        value={deviceIdentifier.mode}
        onValueChange={(mode) =>
          onPatchIdentifier({ mode: mode as DeviceIdentifierConfig["mode"] })
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
              onChange={(event) => onPatchIdentifier({ id: event.target.value })}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">Device name</Label>
            <Input
              className="h-8 text-xs"
              placeholder="router1"
              value={deviceIdentifier.name ?? ""}
              onChange={(event) => onPatchIdentifier({ name: event.target.value })}
            />
          </div>
        </div>
      ) : (
        <p className="text-[11px] text-muted-foreground">
          Uses each device from the upstream inventory step (UUID or name).
        </p>
      )}
    </section>
  );
}

interface UpdateFieldsSectionProps {
  updateFields: NonNullable<import("./types").UpdateNautobotDeviceConfig["update_fields"]>;
  customFieldRows: CustomFieldRow[];
  onPatchField: (key: DeviceFieldKey, patch: Partial<UpdateFieldSpec>) => void;
  onAddCustomFieldRow: () => void;
  onPatchCustomFieldRow: (id: string, patch: Partial<CustomFieldRow>) => void;
  onRemoveCustomFieldRow: (id: string) => void;
}

export function UpdateFieldsSection({
  updateFields,
  customFieldRows,
  onPatchField,
  onAddCustomFieldRow,
  onPatchCustomFieldRow,
  onRemoveCustomFieldRow,
}: UpdateFieldsSectionProps) {
  const enabledFieldCount = useMemo(() => {
    const baseCount = DEVICE_FIELD_DEFINITIONS.filter(({ key }) => updateFields[key]?.enabled)
      .length;
    const customCount = customFieldRows.filter((row) => row.enabled && row.name.trim()).length;
    return baseCount + customCount;
  }, [updateFields, customFieldRows]);

  return (
    <section className="space-y-3 rounded-xl border border-border bg-card p-3 shadow-sm">
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs font-medium">update_fields</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          object
        </Badge>
      </div>
      <p className="text-[11px] leading-4 text-muted-foreground">{UPDATE_FIELD_VALUE_HELP}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {DEVICE_FIELD_DEFINITIONS.map(({ key, label, placeholder }) => (
          <NautobotOptionalFieldRow
            key={key}
            label={label}
            placeholder={placeholder}
            spec={updateFields[key] ?? EMPTY_FIELD_SPEC}
            onChange={(patch) => onPatchField(key, patch)}
          />
        ))}
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-xs font-medium">custom_fields</span>
          <Button
            className="h-7 bg-step text-step-foreground hover:bg-step-hover"
            size="sm"
            type="button"
            onClick={onAddCustomFieldRow}
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
                onChange={(patch) => onPatchCustomFieldRow(row.id, patch)}
                onRemove={() => onRemoveCustomFieldRow(row.id)}
              />
            ))}
          </div>
        )}
      </div>

      <p className="text-[11px] text-muted-foreground">
        {enabledFieldCount} enabled field{enabledFieldCount === 1 ? "" : "s"}. Disabled fields
        are not sent to Nautobot.
      </p>
    </section>
  );
}
