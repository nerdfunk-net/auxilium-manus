"use client";

import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";

import {
  NautobotOptionalFieldRow,
  NautobotRequiredFieldRow,
} from "@/components/features/workflow-steps/shared/nautobot-field-rows";

import { requiredFieldSpec } from "./add-to-nautobot-config";
import type { DeviceFieldKey, DeviceFieldsConfig, UpdateFieldSpec } from "./types";
import {
  DEVICE_FIELD_VALUE_HELP,
  OPTIONAL_DEVICE_FIELD_DEFINITIONS,
  RACK_FIELD_DEFINITIONS,
  REQUIRED_DEVICE_FIELD_DEFINITIONS,
} from "./types";

const EMPTY_FIELD_SPEC: UpdateFieldSpec = { enabled: false, value: "" };

interface DeviceFieldsSectionProps {
  deviceFields: DeviceFieldsConfig;
  onPatchRequiredField: (key: DeviceFieldKey, text: string) => void;
  onPatchOptionalField: (key: DeviceFieldKey, patch: Partial<UpdateFieldSpec>) => void;
}

export function RequiredDeviceFieldsSection({
  deviceFields,
  onPatchRequiredField,
}: Pick<DeviceFieldsSectionProps, "deviceFields" | "onPatchRequiredField">) {
  return (
    <section className="space-y-2 rounded-xl border border-border bg-card p-3 shadow-sm">
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs font-medium">device_fields</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          required
        </Badge>
      </div>
      <p className="text-[11px] leading-4 text-muted-foreground">{DEVICE_FIELD_VALUE_HELP}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {REQUIRED_DEVICE_FIELD_DEFINITIONS.map(({ key, label, placeholder }) => (
          <NautobotRequiredFieldRow
            key={key}
            label={label}
            placeholder={placeholder}
            value={requiredFieldSpec(deviceFields, key).value}
            onChange={(text) => onPatchRequiredField(key, text)}
          />
        ))}
      </div>
    </section>
  );
}

export function OptionalDeviceFieldsSection({
  deviceFields,
  onPatchOptionalField,
  enabledOptionalCount,
  children,
}: Pick<DeviceFieldsSectionProps, "deviceFields" | "onPatchOptionalField"> & {
  enabledOptionalCount: number;
  children?: ReactNode;
}) {
  return (
    <section className="space-y-3 rounded-xl border border-border bg-card p-3 shadow-sm">
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs font-medium">device_fields</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          optional
        </Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {OPTIONAL_DEVICE_FIELD_DEFINITIONS.map(({ key, label, placeholder }) => (
          <NautobotOptionalFieldRow
            key={key}
            label={label}
            placeholder={placeholder}
            spec={deviceFields[key] ?? EMPTY_FIELD_SPEC}
            onChange={(patch) => onPatchOptionalField(key, patch)}
          />
        ))}
      </div>

      {children}

      <p className="text-[11px] text-muted-foreground">
        {enabledOptionalCount} optional field{enabledOptionalCount === 1 ? "" : "s"} enabled.
      </p>
    </section>
  );
}

export function RackFieldsSection({
  deviceFields,
  onPatchOptionalField,
}: Pick<DeviceFieldsSectionProps, "deviceFields" | "onPatchOptionalField">) {
  return (
    <section className="space-y-2 rounded-xl border border-border bg-card p-3 shadow-sm">
      <span className="font-mono text-xs font-medium">rack</span>
      <p className="text-[11px] text-muted-foreground">
        Optional — leave rack empty to skip placement entirely.
      </p>
      <div className="grid gap-2 sm:grid-cols-3">
        {RACK_FIELD_DEFINITIONS.map(({ key, label, placeholder }) => (
          <NautobotOptionalFieldRow
            key={key}
            label={label}
            placeholder={placeholder}
            spec={deviceFields[key] ?? EMPTY_FIELD_SPEC}
            onChange={(patch) => onPatchOptionalField(key, patch)}
          />
        ))}
      </div>
    </section>
  );
}
