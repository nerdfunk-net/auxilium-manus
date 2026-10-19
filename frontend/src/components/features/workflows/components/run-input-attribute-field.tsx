"use client";

import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

import { RunInputDeviceListField } from "../dialogs/run-input-device-list-field";
import { RunInputDeviceTableField } from "./run-input-device-table-field";
import { RunInputReferenceField } from "./run-input-reference-field";
import type { StaticAttributeDef } from "../types/workflow-persistence";
import type { DeviceParamConfig } from "../utils/device-param-hints";

const RUN_INPUT_CLASS = "h-9 text-xs focus-visible:ring-step/40";

interface RunInputAttributeFieldProps {
  id: string;
  attr: StaticAttributeDef;
  value: unknown;
  onChange: (value: unknown) => void;
  deviceParamConfigs: Record<string, DeviceParamConfig>;
}

function stringValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  return value != null ? String(value) : "";
}

/**
 * Renders one workflow static_attribute control for manual Run Inputs or
 * schedule parameter forms. Covers boolean, number, inventory references, and
 * string; other reference kinds are handled by the caller.
 */
export function RunInputAttributeField({
  id,
  attr,
  value,
  onChange,
  deviceParamConfigs,
}: RunInputAttributeFieldProps) {
  if (attr.type === "boolean") {
    return (
      <Switch
        id={id}
        checked={value === true}
        onCheckedChange={(checked) => onChange(checked)}
      />
    );
  }

  if (attr.type === "number") {
    return (
      <Input
        id={id}
        type="number"
        className={RUN_INPUT_CLASS}
        value={value != null && value !== "" ? String(value) : ""}
        onChange={(event) => {
          const raw = event.target.value;
          onChange(raw === "" ? "" : Number(raw));
        }}
      />
    );
  }

  if (attr.type === "secret") {
    return (
      <Input
        id={id}
        type="password"
        autoComplete="new-password"
        className={RUN_INPUT_CLASS}
        value={stringValue(value)}
        placeholder="Value is sealed on submit and cannot be read again"
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }

  if (attr.type === "reference" && attr.ref_kind === "inventory") {
    return <RunInputReferenceField value={value} onChange={onChange} />;
  }

  const text = stringValue(value);
  const deviceConfig = deviceParamConfigs[attr.name];

  if (deviceConfig?.lookupMode === "nautobot_search" && deviceConfig.sourceId) {
    return (
      <RunInputDeviceListField
        value={text}
        sourceId={deviceConfig.sourceId}
        defaultNetworkDriver={deviceConfig.defaultNetworkDriver}
        onChange={(next) => onChange(next)}
      />
    );
  }

  if (deviceConfig) {
    return (
      <RunInputDeviceTableField
        value={text}
        defaultNetworkDriver={deviceConfig.defaultNetworkDriver}
        onChange={(next) => onChange(next)}
      />
    );
  }

  return (
    <Input
      id={id}
      type="text"
      className={RUN_INPUT_CLASS}
      value={text}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}
