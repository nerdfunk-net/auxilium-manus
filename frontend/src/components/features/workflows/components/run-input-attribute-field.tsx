"use client";

import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

import { RunInputDeviceListField } from "../dialogs/run-input-device-list-field";
import type { StaticAttributeDef } from "../types/workflow-persistence";
import type { DeviceParamConfig } from "../utils/device-param-hints";

const RUN_INPUT_CLASS = "h-9 text-xs focus-visible:ring-step/40";
const RUN_INPUT_DEVICE_TEXTAREA_CLASS =
  "min-h-[72px] font-mono text-xs focus-visible:ring-step/40";

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
 * schedule parameter forms. Reference-typed attributes are handled by the
 * caller — this component covers boolean, number, and string only.
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

  const text = stringValue(value);
  const deviceConfig = deviceParamConfigs[attr.name];

  if (deviceConfig?.lookupMode === "nautobot_search" && deviceConfig.sourceId) {
    return (
      <RunInputDeviceListField
        value={text}
        sourceId={deviceConfig.sourceId}
        onChange={(next) => onChange(next)}
      />
    );
  }

  if (deviceConfig) {
    return (
      <Textarea
        id={id}
        rows={3}
        className={RUN_INPUT_DEVICE_TEXTAREA_CLASS}
        value={text}
        placeholder="One device per line — hostname, IP, or name,ip_address"
        onChange={(event) => onChange(event.target.value)}
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
