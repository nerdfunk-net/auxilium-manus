"use client";

import { Input } from "@/components/ui/input";

import { CheckboxField } from "./checkbox-field";
import { FieldHeader } from "./field-header";
import { MAX_SOCKET_TIMEOUT, MIN_SOCKET_TIMEOUT } from "./device-file-transfer";

interface TransferTextFieldProps {
  name: string;
  type?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: string;
}

/** A single-line monospace text field with its `name [type]` caption and hint. */
export function TransferTextField({
  name,
  type = "string",
  value,
  onChange,
  placeholder,
  hint,
}: TransferTextFieldProps) {
  return (
    <div className="space-y-1.5">
      <FieldHeader name={name} type={type} />
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="h-8 font-mono text-xs"
      />
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

interface OverwriteFieldProps {
  overwrite: boolean;
  onChange: (checked: boolean) => void;
  description?: string;
}

export function OverwriteField({
  overwrite,
  onChange,
  description = "Replace the destination file if it already exists.",
}: OverwriteFieldProps) {
  return (
    <div className="space-y-1.5">
      <CheckboxField
        id="overwrite"
        label="overwrite"
        checked={overwrite}
        onCheckedChange={onChange}
        description={description}
      />
      {overwrite ? (
        <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
          This will replace the existing file on the device if one exists at this path.
        </p>
      ) : null}
    </div>
  );
}

interface SocketTimeoutFieldProps {
  socketTimeout: number;
  onChange: (value: string) => void;
  hint: string;
}

export function SocketTimeoutField({ socketTimeout, onChange, hint }: SocketTimeoutFieldProps) {
  return (
    <div className="space-y-1.5">
      <FieldHeader name="socket_timeout" type="integer" />
      <Input
        type="number"
        min={MIN_SOCKET_TIMEOUT}
        max={MAX_SOCKET_TIMEOUT}
        value={socketTimeout}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 font-mono text-xs"
      />
      <p className="text-[11px] text-muted-foreground">{hint}</p>
    </div>
  );
}

interface NetworkDriverOverrideFieldProps {
  value: string;
  onChange: (value: string) => void;
}

export function NetworkDriverOverrideField({ value, onChange }: NetworkDriverOverrideFieldProps) {
  return (
    <TransferTextField
      name="network_driver_override"
      value={value}
      onChange={onChange}
      placeholder="cisco_ios (optional)"
      hint="Overrides each device's network driver for Netmiko in this step."
    />
  );
}
